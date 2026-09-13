from ._base import *


class CarbonIntensityApiView(APIView):

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
                 "UTC time", "creation_time (UTC)", "version", "region_code", "carbon_intensity_avg_lifecycle", 
                 "carbon_intensity_avg_direct", "cabon_intensity_unit"
            ]
        
            final_list = []
        
            if region_code == 'all':
                cache_key_all = "ci_latest_all_regions"
                cached_all = cache.get(cache_key_all)
                if cached_all:
                    return Response({
                        "data": cached_all,
                        "carbon_cast_version": carbon_cast_version
                    }, status=status.HTTP_200_OK)

                # Fetch all regions in one single PostgreSQL DISTINCT ON query
                latest_objs = EmissionActual.objects.filter(
                    region__in=regions
                ).order_by('region', '-ts').distinct('region')
                latest_by_region = {obj.region: obj for obj in latest_objs}

                for rc in regions:
                    obj = latest_by_region.get(rc)
                    if not obj:
                        continue
                    temp_dict = {
                        fields[0]: obj.ts.isoformat(),
                        fields[1]: obj.data.get("creation_time (UTC)") or obj.data.get("creation_time") or "",
                        fields[2]: obj.data.get("version") or "",
                        fields[3]: rc,
                        fields[4]: float(obj.lifecycle) if obj.lifecycle is not None else float(
                            obj.data.get("carbon_intensity_avg_lifecycle")
                            or obj.data.get("carbon_intensity")
                            or obj.data.get("lifecycle")
                            or obj.data.get("value")
                            or 0
                        ),
                        fields[5]: float(obj.direct) if obj.direct is not None else float(
                            obj.data.get("carbon_intensity_avg_direct")
                            or obj.data.get("carbon_intensity")
                            or obj.data.get("direct")
                            or obj.data.get("value")
                            or 0
                        ),
                        fields[6]: obj.data.get("carbon_intensity_unit", "gCO2eg/kWh")
                    }
                    final_list.append(temp_dict)
                    cache.set(f"ci_latest_{rc}", temp_dict, 60)

                cache.set(cache_key_all, final_list, 60)
                return Response({
                    "data": final_list,
                    "carbon_cast_version": carbon_cast_version
                }, status=status.HTTP_200_OK)
            else:
                cache_key = f"ci_latest_{region_code}"
                cached = cache.get(cache_key)
                if cached:
                    return Response({
                        "data": [cached],
                        "carbon_cast_version": carbon_cast_version
                    }, status=status.HTTP_200_OK)

                obj = EmissionActual.objects.filter(region=region_code).order_by('-ts').first()
                if obj:
                    temp_dict = {
                        fields[0]: obj.ts.isoformat(),
                        fields[1]: obj.data.get("creation_time (UTC)") or obj.data.get("creation_time") or "",
                        fields[2]: obj.data.get("version") or "",
                        fields[3]: region_code,
                        fields[4]: float(obj.lifecycle) if obj.lifecycle is not None else float(
                            obj.data.get("carbon_intensity_avg_lifecycle")
                            or obj.data.get("carbon_intensity")
                            or obj.data.get("lifecycle")
                            or obj.data.get("value")
                            or 0
                        ),
                        fields[5]: float(obj.direct) if obj.direct is not None else float(
                            obj.data.get("carbon_intensity_avg_direct")
                            or obj.data.get("carbon_intensity")
                            or obj.data.get("direct")
                            or obj.data.get("value")
                            or 0
                        ),
                        fields[6]: obj.data.get("carbon_intensity_unit", "gCO2eg/kWh")
                    }
                    final_list.append(temp_dict)
                    cache.set(cache_key, temp_dict, 60)

                return Response({
                    "data": final_list,
                    "carbon_cast_version": carbon_cast_version
                }, status=status.HTTP_200_OK)
        
#2    
class CarbonIntensityHistoryApiView(APIView):
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

    def get(self, request, *args, **kwargs): #TODO:#focus on this
        if permissions.AllowAny not in permission_classes:
            user = request.user
            print("User:",user)
            if not check_throttle_limit(user):
                return Response({
                    "status": "fail",
                    "message": "Throttle limit reached",
                    "carbon_cast_version": carbon_cast_version
                }, status=status.HTTP_429_TOO_MANY_REQUESTS, headers={'Retry-After': 86400})
        #from here
        class QueryParamsSerializer(serializers.Serializer):
            region_code = serializers.CharField(required=False)

        # Deserialize and validate query parameters
        query_params_serializer = QueryParamsSerializer(data=request.query_params)
        if query_params_serializer.is_valid():
            region_code = query_params_serializer.validated_data.get('region_code')
            
            if region_code == 'all':
                regions = US_region_codes
                print(f"[DEBUG] Requesting ALL regions. Total available: {len(US_region_codes)}")
                print(f"[DEBUG] All regions: {US_region_codes}")
            elif region_code in US_region_codes:
                regions = [region_code]
            else:
                return Response({"error": "Invalid region code parameter"}, status=status.HTTP_400_BAD_REQUEST)
        date = request.query_params.get('date', '')
        hour = request.query_params.get('hour', None)  # Get the hour parameter
        start_time = time.time()
        print(f"[PERF START] CarbonIntensityHistoryApiView for date: {date}, hour: {hour}, Requested regions: {len(regions)} regions")
                  

        field_names = [
                        "UTC time", "creation_time (UTC)", "version", "region_code", "carbon_intensity_avg_lifecycle",
                        "carbon_intensity_avg_direct", "carbon_intensity_unit"
        ]

        final_list =[]
        # Initialize metadata tracking for all regions
        overall_metadata = None
        regions_with_data = []
        regions_without_data = []
        regions_from_csv = []
        regions_from_db = []
        
        # Parse date once before the loop
        try:
            from datetime import datetime
            date_obj = datetime.strptime(date, "%Y-%m-%d").date() if date else None
            print(f"[DEBUG] Successfully parsed date: {date_obj}")
        except Exception as e:
            print(f"[DEBUG] Failed to parse date '{date}': {e}, using default date")
            from datetime import datetime
            date_obj = datetime.now().date()  # Default to today
        
        # Prepare hour filter
        hour_int = None
        if hour is not None:
            try:
                hour_int = int(hour)
                print(f"[DEBUG] Hour filter: {hour_int}")
            except (ValueError, TypeError):
                print(f"[DEBUG] Invalid hour parameter: {hour}")
        
        # OPTIMIZATION: Batch query all regions at once when possible
        if len(regions) > 1 and date_obj:  # Batch for any multiple regions
            print(f"[DEBUG] Using OPTIMIZED BATCH QUERY for {len(regions)} regions")
            
            from datetime import time as dtime, timezone as dtz
            start_ts = datetime.combine(date_obj, dtime.min).replace(tzinfo=dtz.utc)
            end_ts = datetime.combine(date_obj, dtime.max).replace(tzinfo=dtz.utc)
            
            # Build optimized batch query using indexed ts range
            base_query = EmissionActual.objects.filter(
                region__in=regions,
                ts__range=(start_ts, end_ts)
            ).only('region', 'ts', 'lifecycle', 'direct', 'data')
            
            if hour_int is not None:
                base_query = base_query.filter(ts__hour=hour_int)
            
            # DB FALLBACK: If requested date has no data in DB, find latest available date in DB
            if not base_query.exists():
                latest_ts = EmissionActual.objects.order_by('-ts').values_list('ts', flat=True).first()
                if latest_ts:
                    actual_date = latest_ts.date()
                    fb_start = datetime.combine(actual_date, dtime.min).replace(tzinfo=dtz.utc)
                    fb_end = datetime.combine(actual_date, dtime.max).replace(tzinfo=dtz.utc)
                    base_query = EmissionActual.objects.filter(
                        region__in=regions,
                        ts__range=(fb_start, fb_end)
                    ).only('region', 'ts', 'lifecycle', 'direct', 'data')
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
                    print(f"[DEBUG] Database fallback used: requested {date_obj}, using {actual_date}")
            
            # Use values_list with named=True for faster processing
            batch_results = base_query.order_by('region', 'ts').values_list(
                'region', 'ts', 'lifecycle', 'direct', 'data', named=True
            )
            
            # Group results by region using iterator for memory efficiency
            from collections import defaultdict
            region_data_map = defaultdict(list)
            
            # Process in chunks to avoid loading all into memory at once
            for row in batch_results.iterator(chunk_size=1000):
                region_data_map[row.region].append(row)
            
            print(f"[DEBUG] Batch query found data for {len(region_data_map)} regions")
            
            # Process each region's data
            for region_code in regions:
                # Check cache first
                if hour_int is not None:
                    cache_key = f"ci_history_{region_code}_{date}_hour_{hour}"
                else:
                    cache_key = f"ci_history_{region_code}_{date}"
                
                cached = cache.get(cache_key)
                if cached:
                    print(f"[DEBUG] Cache hit for {cache_key}, adding {len(cached)} items")
                    final_list.extend(cached)
                    regions_with_data.append(region_code)
                    continue
                
                # Use batch query results
                if region_code in region_data_map:
                    temp_batch = []
                    for row_data in region_data_map[region_code]:
                        # Faster processing with named tuple access
                        data_dict = row_data.data or {}
                        temp_dict = {
                            field_names[0]: row_data.ts.isoformat(),
                            field_names[1]: data_dict.get("creation_time (UTC)", "") or data_dict.get("creation_time", ""),
                            field_names[2]: data_dict.get("version", ""),
                            field_names[3]: region_code,
                            field_names[4]: safe_float(row_data.lifecycle, 0.0),
                            field_names[5]: safe_float(row_data.direct, 0.0),
                            field_names[6]: data_dict.get("carbon_intensity_unit", "gCO2eg/kWh")
                        }
                        temp_batch.append(temp_dict)
                        final_list.append(temp_dict)
                    
                    cache.set(cache_key, temp_batch, 10)
                    print(f"[DEBUG] Batch processed {len(temp_batch)} items for region {region_code}")
                    if len(temp_batch) > 0:
                        regions_from_db.append(region_code)
                        regions_with_data.append(region_code)
                    else:
                        regions_without_data.append(region_code)
                else:
                    # No data in batch results, try CSV fallback
                    print(f"[DEBUG] No DB data for region {region_code}, trying CSV fallback")
                    regions_without_data.append(region_code)
                    result = get_actual_value_file_by_date_with_metadata(region_code, date)
                    csv_file_a = result["lifecycle_file"]
                    csv_file_b = result["direct_file"]
                    region_metadata = result["metadata"]
                    if region_metadata and region_metadata.get("overall_fallback"):
                        overall_metadata = region_metadata
                    try:
                        if not csv_file_a or not os.path.exists(csv_file_a) or not csv_file_b or not os.path.exists(csv_file_b):
                            continue
                        with open(csv_file_a) as file:
                            lines_csv1 = file.readlines()
                        with open(csv_file_b) as file:
                            lines_csv2 = file.readlines()
                        values_csv1 = [line.strip().split(',') for line in lines_csv1]
                        values_csv2 = [line.strip().split(',') for line in lines_csv2]
                        temp_batch = []
                        min_len = min(len(values_csv1), len(values_csv2))
                        for i in range(1, min_len):
                            if len(values_csv1[i]) < 5 or len(values_csv2[i]) < 5:
                                continue
                            if hour is not None:
                                try:
                                    hour_int = int(hour)
                                    csv_timestamp = values_csv1[i][1]
                                    if ' ' in csv_timestamp:
                                        csv_hour = int(csv_timestamp.split(' ')[1].split(':')[0])
                                        if csv_hour != hour_int:
                                            continue
                                except (ValueError, IndexError, TypeError):
                                    pass
                            
                            temp_dict= {}
                            temp_dict[field_names[0]] = values_csv1[i][1]
                            temp_dict[field_names[1]] = values_csv1[i][2]
                            temp_dict[field_names[2]] = values_csv1[i][3]
                            temp_dict[field_names[3]] = region_code
                            temp_dict[field_names[4]] = safe_float(values_csv1[i][4], 0.0)
                            temp_dict[field_names[5]] = safe_float(values_csv2[i][4], 0.0)
                            temp_dict[field_names[6]] = "gCO2eg/kWh"
                            temp_batch.append(temp_dict)
                            final_list.append(temp_dict)
                        cache.set(cache_key, temp_batch, 10)
                        if len(temp_batch) > 0:
                            regions_from_csv.append(region_code)
                    except Exception as e:
                        print(f"[DEBUG] Error reading CSV for region {region_code}: {e}")
        else:
            # Sequential processing for single region or when no date
            print(f"[DEBUG] Using SEQUENTIAL processing for {len(regions)} regions")
            for region_code in regions:
                # Include hour in cache key when hour parameter is provided
                if hour is not None:
                    cache_key = f"ci_history_{region_code}_{date}_hour_{hour}"
                else:
                    cache_key = f"ci_history_{region_code}_{date}"
                
                cached = cache.get(cache_key)
                if cached:
                    print(f"[DEBUG] Cache hit for {cache_key}, adding {len(cached)} items")
                    final_list.extend(cached)
                    continue

                if date_obj:
                    # Optimize query with only() to fetch needed fields
                    base_query = EmissionActual.objects.filter(
                        region=region_code,
                        ts__date=date_obj
                    ).only('ts', 'lifecycle', 'direct', 'data')
                    
                    # Check if hour parameter is provided
                    if hour_int is not None:
                        # Filter by both date AND hour when hour is provided
                        rows = base_query.filter(ts__hour=hour_int).order_by('ts')
                        print(f"[DEBUG] Querying for region {region_code} on date {date_obj} hour {hour_int}")
                    else:
                        # No hour parameter, return all hours for the date
                        rows = base_query.order_by('ts')
                        print(f"[DEBUG] Querying for region {region_code} on date {date_obj} (all hours)")
                else:
                    # Default to today's date if no date provided
                    from datetime import datetime
                    default_date = datetime.now().date()
                    print(f"[DEBUG] Using default date: {default_date}")
                    rows = EmissionActual.objects.filter(region=region_code, ts__date=default_date).order_by('ts')
                    print(f"[DEBUG] Found {rows.count()} rows for default date")

                # Initialize metadata for this region
                region_metadata = None
                
                if not rows.exists():
                    print(f"[DEBUG] No DB data for region {region_code} on {date_obj or 'no valid date'}")
                    regions_without_data.append(region_code)
                    # fallback to CSV-compatible behavior with metadata
                    result = get_actual_value_file_by_date_with_metadata(region_code, date)
                    csv_file_a = result["lifecycle_file"]
                    csv_file_b = result["direct_file"]
                    region_metadata = result["metadata"]
                    # Track overall metadata across all regions
                    if region_metadata and region_metadata.get("overall_fallback"):
                        overall_metadata = region_metadata
                    try:
                        if not csv_file_a or not os.path.exists(csv_file_a) or not csv_file_b or not os.path.exists(csv_file_b):
                            continue
                        with open(csv_file_a) as file:
                            lines_csv1 = file.readlines()
                        with open(csv_file_b) as file:
                            lines_csv2 = file.readlines()
                        values_csv1 = [line.strip().split(',') for line in lines_csv1]
                        values_csv2 = [line.strip().split(',') for line in lines_csv2]
                        # Create temp_batch for this region only
                        temp_batch = []
                        min_len = min(len(values_csv1), len(values_csv2))
                        for i in range(1, min_len):
                            if len(values_csv1[i]) < 5 or len(values_csv2[i]) < 5:
                                continue
                            # If hour parameter is specified, filter by hour
                            if hour is not None:
                                try:
                                    hour_int = int(hour)
                                    # Extract hour from CSV timestamp (format: "YYYY-MM-DD HH:MM:SS")
                                    csv_timestamp = values_csv1[i][1]
                                    if ' ' in csv_timestamp:
                                        csv_hour = int(csv_timestamp.split(' ')[1].split(':')[0])
                                        if csv_hour != hour_int:
                                            continue  # Skip this row if hour doesn't match
                                except (ValueError, IndexError, TypeError):
                                    pass  # If can't parse hour, include the row
                            
                            temp_dict= {}
                            temp_dict[field_names[0]] = values_csv1[i][1]
                            temp_dict[field_names[1]] = values_csv1[i][2]
                            temp_dict[field_names[2]] = values_csv1[i][3]
                            temp_dict[field_names[3]] = region_code
                            temp_dict[field_names[4]] = safe_float(values_csv1[i][4], 0.0)
                            temp_dict[field_names[5]] = safe_float(values_csv2[i][4], 0.0)
                            temp_dict[field_names[6]] = "gCO2eg/kWh"
                            temp_batch.append(temp_dict)
                            final_list.append(temp_dict)
                        # Cache only this region's data, not the entire final_list
                        cache.set(cache_key, temp_batch, 10)
                        print(f"[DEBUG] Added {len(temp_batch)} items from CSV for region {region_code} (hour filter: {hour})")
                        if len(temp_batch) > 0:
                            regions_from_csv.append(region_code)
                        continue
                    except Exception as e:
                        print(f"[DEBUG] Error reading CSV for region {region_code}: {e}")
                        continue

                temp_batch = []
                # Use iterator for memory efficiency
                for obj in rows.iterator(chunk_size=100):
                    data_dict = obj.data or {}
                    temp_dict = {
                        field_names[0]: obj.ts.isoformat(),
                        field_names[1]: data_dict.get("creation_time (UTC)", "") or data_dict.get("creation_time", ""),
                        field_names[2]: data_dict.get("version", ""),
                        field_names[3]: region_code,
                        field_names[4]: safe_float(obj.lifecycle, 0.0),
                        field_names[5]: safe_float(obj.direct, 0.0),
                        field_names[6]: data_dict.get("carbon_intensity_unit", "gCO2eg/kWh")
                    }
                    temp_batch.append(temp_dict)
                    final_list.append(temp_dict)
                
                # Cache with hour-specific key when hour parameter is provided
                if hour is not None:
                    cache_key = f"ci_history_{region_code}_{date}_hour_{hour}"
                else:
                    cache_key = f"ci_history_{region_code}_{date}"
                
                cache.set(cache_key, temp_batch, 10)
                print(f"[DEBUG] Cached {len(temp_batch)} items for region {region_code} with key: {cache_key}")
                if len(temp_batch) > 0:
                    regions_from_db.append(region_code)
                    regions_with_data.append(region_code)
                else:
                    regions_without_data.append(region_code)
        
        total_time = (time.time() - start_time) * 1000
        expected_items = len(regions) * (1 if hour is not None else 24)
        regions_responded = len(set(regions_with_data + regions_from_csv))
        
        # Calculate fallback percentage to determine if overall_fallback should be True
        # Only set overall_fallback = True when MAJORITY (>50%) of regions needed fallback
        total_regions_requested = len(regions)
        fallback_count = len(regions_from_csv)
        db_count = len(regions_from_db)
        
        # Calculate fallback percentage (regions using CSV fallback / total regions with data)
        regions_with_any_data = fallback_count + db_count
        if regions_with_any_data > 0:
            fallback_percentage = fallback_count / regions_with_any_data
        else:
            fallback_percentage = 0.0
        
        # Determine if overall_fallback should be True based on majority threshold
        # overall_fallback = True only if more than 50% of regions needed fallback
        should_show_fallback_warning = fallback_percentage > 0.5
        
        print(f"[PERF END] Total API time: {total_time:.2f}ms for {len(final_list)} items")
        print(f"[PERF] Expected {expected_items} items (from {len(regions)} regions), got {len(final_list)} items")
        print(f"[DEBUG] REGION SUMMARY:")
        print(f"  - Requested regions: {total_regions_requested}")
        print(f"  - Regions with data: {regions_responded} ({db_count} from DB, {fallback_count} from CSV)")
        print(f"  - Regions without any data: {len(regions_without_data)}")
        print(f"  - Fallback percentage: {fallback_percentage:.1%} ({fallback_count}/{regions_with_any_data})")
        print(f"  - Should show fallback warning: {should_show_fallback_warning}")
        if len(regions_without_data) > 0:
            print(f"  - Missing regions: {regions_without_data[:10]}{'...' if len(regions_without_data) > 10 else ''}")
        if total_time > 5000:
            print(f"[PERF ALERT] 🔴 API response time exceeded 5 seconds: {total_time:.2f}ms")
        elif total_time > 1000:
            print(f"[PERF WARNING] 🟡 API response time exceeded 1 second: {total_time:.2f}ms")
        
        # Build response with metadata if fallback was used
        response = {
            "data": final_list,
            "carbon_cast_version": carbon_cast_version,
        }
        
        # Attach fallback metadata when fallback date was used
        is_fallback = should_show_fallback_warning or (overall_metadata and overall_metadata.get("overall_fallback", False))
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
            
        # Create response with appropriate headers
        http_response = Response(response, status=status.HTTP_200_OK)
        if is_fallback and overall_metadata:
            http_response["X-Fallback-Used"] = "true"
            http_response["X-Actual-Date-Lifecycle"] = overall_metadata.get("lifecycle_actual_date", date)
            http_response["X-Actual-Date-Direct"] = overall_metadata.get("direct_actual_date", date)
        
        return http_response

#4  
