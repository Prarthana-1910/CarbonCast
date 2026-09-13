from ._base import *


class EnergySourcesApiView(APIView):
    authentication_classes = authentication_classes
    permission_classes = permission_classes

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter('region_code', openapi.IN_QUERY, description="Region code parameter (e.g., 'AECI').", type=openapi.TYPE_STRING),
        ],
        responses={
            200: 'HTTP 200 OK - Success response description',
            400: 'HTTP 400 Bad Request - Description of possible error responses',
        }
    )

    def get(self, request, *args, **kwargs):

        if permissions.AllowAny not in permission_classes:
            user = request.user
            print("User:",user)
            if not check_throttle_limit(user):
                return Response({
                    "status": "fail",
                    "message": "Throttle limit reached",
                    "carbon_cast_version": carbon_cast_version
                }, status=status.HTTP_429_TOO_MANY_REQUESTS, headers={'Retry-After': 86400})

        # Define the serializer for validating query parameters
        class QueryParamsSerializer(serializers.Serializer):
            region_code = serializers.CharField(required=False)

        # Deserialize and validate query parameters
        query_params_serializer = QueryParamsSerializer(data=request.query_params)
        if query_params_serializer.is_valid():
            region_code = query_params_serializer.validated_data.get('region_code')
            
            if region_code == 'all':
                regions = US_region_codes
            elif region_code in US_region_codes:
                regions = [region_code]
            else:
                return Response({"error": "Invalid region code parameter"}, status=status.HTTP_400_BAD_REQUEST)

            fields = [
                "UTC time", "creation_time (UTC)", "version", "region_code", "coal", "nat_gas", "nuclear",
                "oil", "hydro", "solar", "wind", "other"
            ]

            final_list = []

            if region_code == 'all':
                cache_key_all = "energy_latest_all_regions"
                cached_all = cache.get(cache_key_all)
                if cached_all:
                    return Response({"data": cached_all, "carbon_cast_version": carbon_cast_version}, status=status.HTTP_200_OK)

                latest_objs = EmissionActual.objects.filter(
                    region__in=regions
                ).order_by('region', '-ts').distinct('region')
                latest_by_region = {obj.region: obj for obj in latest_objs}

                for rc in regions:
                    obj = latest_by_region.get(rc)
                    if not obj:
                        continue
                    response_data = {
                        "UTC time": obj.ts.isoformat(),
                        "creation_time (UTC)": obj.data.get("creation_time (UTC)") or obj.data.get("creation_time") or "",
                        "version": obj.data.get("version") or "",
                        "region_code": rc,
                    }
                    for field in fields[4:]:
                        response_data[field] = obj.data.get(field, "0")

                    final_list.append(response_data)
                    cache.set(f"energy_latest_{rc}", response_data, 60)

                cache.set(cache_key_all, final_list, 60)
                return Response({"data": final_list, "carbon_cast_version": carbon_cast_version}, status=status.HTTP_200_OK)
            else:
                cache_key = f"energy_latest_{region_code}"
                cached = cache.get(cache_key)
                if cached:
                    return Response({"data": [cached], "carbon_cast_version": carbon_cast_version}, status=status.HTTP_200_OK)

                obj = EmissionActual.objects.filter(region=region_code).order_by('-ts').first()
                if obj:
                    response_data = {
                        "UTC time": obj.ts.isoformat(),
                        "creation_time (UTC)": obj.data.get("creation_time (UTC)") or obj.data.get("creation_time") or "",
                        "version": obj.data.get("version") or "",
                        "region_code": region_code,
                    }
                    for field in fields[4:]:
                        response_data[field] = obj.data.get(field, "0")

                    final_list.append(response_data)
                    cache.set(cache_key, response_data, 60)

                return Response({"data": final_list, "carbon_cast_version": carbon_cast_version}, status=status.HTTP_200_OK)
            

#3 
class EnergySourcesHistoryApiView(APIView):
    authentication_classes = authentication_classes
    permission_classes = permission_classes

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter('region_code', openapi.IN_QUERY, description="Region code parameter (e.g., 'AECI').", type=openapi.TYPE_STRING),
            openapi.Parameter('date', openapi.IN_QUERY, description="Date parameter (in the format: 'YYYY-MM-DD').", type=openapi.TYPE_STRING),
        ],
        responses={
            200: 'HTTP 200 OK - Success response description',
            400: 'HTTP 400 Bad Request - Description of possible error responses',
        }
    )

    def get(self, request, *args, **kwargs):

        if permissions.AllowAny not in permission_classes:
            user = request.user
            print("User:",user)
            if not check_throttle_limit(user):
                return Response({
                    "status": "fail",
                    "message": "Throttle limit reached",
                    "carbon_cast_version": carbon_cast_version
                }, status=status.HTTP_429_TOO_MANY_REQUESTS, headers={'Retry-After': 86400})

        class QueryParamsSerializer(serializers.Serializer):
            region_code = serializers.CharField(required=False)
        
        query_params_serializer = QueryParamsSerializer(data=request.query_params)
        if query_params_serializer.is_valid():
            region_code = query_params_serializer.validated_data.get('region_code')
            
            if region_code == 'all':
                regions = US_region_codes
            elif region_code in US_region_codes:
                regions = [region_code]
            else:
                return Response({"error": "Invalid region code parameter"}, status=status.HTTP_400_BAD_REQUEST)
        date = request.query_params.get('date', '')
        hour = request.query_params.get('hour', None)  # Get the hour parameter
        print(f"[EnergySourcesHistoryApiView] Requested date: {date}, hour: {hour}, Regions: {regions}")
        
        fields = [
            "UTC time", "creation_time (UTC)", "version", "region_code", "coal", "nat_gas", "nuclear",
            "oil", "hydro", "solar", "wind", "other"
        ]
        
        final_list =[]
        # Initialize metadata tracking for all regions
        overall_metadata = None
        # Track which regions came from DB vs CSV for fallback percentage calculation
        regions_from_db = []
        regions_from_csv = []
        
        # Parse hour parameter once before the loop
        hour_int = None
        if hour is not None:
            try:
                hour_int = int(hour)
                print(f"[DEBUG EnergySourcesHistory] Hour filter: {hour_int}")
            except (ValueError, TypeError):
                print(f"[DEBUG EnergySourcesHistory] Invalid hour parameter: {hour}")
        
        # Parse date once
        try:
            from datetime import datetime, time as dtime, timezone as dtz
            date_obj = datetime.strptime(date, "%Y-%m-%d").date() if date else None
        except Exception:
            date_obj = None

        if not date_obj:
            from datetime import datetime, time as dtime, timezone as dtz
            date_obj = datetime.now().date()

        from datetime import time as dtime, timezone as dtz
        start_ts = datetime.combine(date_obj, dtime.min).replace(tzinfo=dtz.utc)
        end_ts = datetime.combine(date_obj, dtime.max).replace(tzinfo=dtz.utc)

        # Build base query
        base_query = EmissionActual.objects.filter(
            region__in=regions,
            ts__range=(start_ts, end_ts)
        ).only('region', 'ts', 'data')

        if hour_int is not None:
            base_query = base_query.filter(ts__hour=hour_int)

        # Database fallback if no rows for requested date
        if not base_query.exists():
            latest_ts = EmissionActual.objects.order_by('-ts').values_list('ts', flat=True).first()
            if latest_ts:
                actual_date = latest_ts.date()
                fb_start = datetime.combine(actual_date, dtime.min).replace(tzinfo=dtz.utc)
                fb_end = datetime.combine(actual_date, dtime.max).replace(tzinfo=dtz.utc)
                base_query = EmissionActual.objects.filter(
                    region__in=regions,
                    ts__range=(fb_start, fb_end)
                ).only('region', 'ts', 'data')
                if hour_int is not None:
                    base_query = base_query.filter(ts__hour=hour_int)
                overall_metadata = {
                    "overall_fallback": True,
                    "lifecycle_fallback": True,
                    "direct_fallback": True,
                    "lifecycle_actual_date": str(actual_date),
                    "direct_actual_date": str(actual_date),
                    "requested_date": str(date_obj),
                    "message": f"Data from {actual_date} (requested {date_obj})"
                }
                print(f"[DEBUG EnergySourcesHistory] DB fallback used: requested {date_obj}, using {actual_date}")

        from collections import defaultdict
        region_data_map = defaultdict(list)
        for obj in base_query.order_by('region', 'ts').iterator(chunk_size=1000):
            region_data_map[obj.region].append(obj)

        for region_code in regions:
            if hour is not None:
                cache_key = f"energy_history_{region_code}_{date}_hour_{hour}"
            else:
                cache_key = f"energy_history_{region_code}_{date}"

            cached = cache.get(cache_key)
            if cached:
                final_list.extend(cached)
                regions_from_db.append(region_code)
                continue

            if region_code in region_data_map:
                temp_batch = []
                for obj in region_data_map[region_code]:
                    temp_dict = {
                        "UTC time": obj.ts.isoformat(),
                        "creation_time (UTC)": obj.data.get("creation_time (UTC)") or obj.data.get("creation_time") or "",
                        "version": obj.data.get("version") or "",
                        "region_code": region_code,
                    }
                    for field in fields[4:]:
                        temp_dict[field] = obj.data.get(field, "0")
                    temp_batch.append(temp_dict)
                    final_list.append(temp_dict)
                cache.set(cache_key, temp_batch, 60)
                if len(temp_batch) > 0:
                    regions_from_db.append(region_code)

        # Calculate fallback percentage to determine if overall_fallback should be True
        total_regions_requested = len(regions)
        fallback_count = len(regions_from_csv)
        db_count = len(regions_from_db)
        
        regions_with_any_data = fallback_count + db_count
        if regions_with_any_data > 0:
            fallback_percentage = fallback_count / regions_with_any_data
        else:
            fallback_percentage = 0.0
        
        should_show_fallback_warning = fallback_percentage > 0.5
        is_fallback = should_show_fallback_warning or (overall_metadata and overall_metadata.get("overall_fallback", False))

        response = {
            "data": final_list,
            "carbon_cast_version": carbon_cast_version
        }
        
        if is_fallback and overall_metadata:
            fallback_dict = {
                "message": overall_metadata.get("message", "Fallback date was used for majority of regions"),
                "requested_date": overall_metadata.get("requested_date", str(date)),
                "lifecycle_actual_date": overall_metadata.get("lifecycle_actual_date"),
                "direct_actual_date": overall_metadata.get("direct_actual_date"),
                "lifecycle_fallback": overall_metadata.get("lifecycle_fallback", True),
                "direct_fallback": overall_metadata.get("direct_fallback", True),
                "overall_fallback": True,
                "fallback_stats": {
                    "total_regions": total_regions_requested,
                    "regions_from_db": db_count,
                    "regions_from_csv": fallback_count,
                    "fallback_percentage": round(fallback_percentage * 100, 1)
                }
            }
            response["fallback_metadata"] = fallback_dict
            response["metadata"] = fallback_dict
            
        http_response = Response(response, status=status.HTTP_200_OK)
        if is_fallback and overall_metadata:
            http_response["X-Fallback-Used"] = "true"
            http_response["X-Actual-Date-Lifecycle"] = overall_metadata.get("lifecycle_actual_date", date)
            http_response["X-Actual-Date-Direct"] = overall_metadata.get("direct_actual_date", date)
            
        return http_response

#5
