from ._base import *


class CarbonIntensityForecastsApiView(APIView):
    authentication_classes = authentication_classes
    permission_classes = permission_classes

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter('regionCode', openapi.IN_QUERY, description="Region code parameter (e.g., 'AECI').", type=openapi.TYPE_STRING),
            openapi.Parameter('forecastPeriod', openapi.IN_QUERY, description="Forecast period in hours ('24h', '48h', '96h', '168h').", type=openapi.TYPE_STRING, default='24h'),
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

        region_code = request.query_params.get('regionCode', '')  
        f = request.query_params.get('forecastPeriod', '24h')

        f_value = str(f)
        final_interval = int(f_value[:-1] if f_value.endswith('h') else f_value)
        forecastPeriod = min(int(final_interval), 168)

        # Get the current date instead of using hardcoded date
        from datetime import datetime
        date = datetime.now().strftime('%Y-%m-%d')
        print(f"[CarbonIntensityForecastsApiView] Using date: {date} (was previously hardcoded as 2023-09-17)")

        # Try to read forecasts from DB first
        field_names = [
                        "UTC time", "creation_time (UTC)", "version", "region_code", "carbon_intensity_avg_lifecycle",
                        "carbon_intensity_avg_direct", "carbon_intensity_unit"
        ]
        cache_key = f"ci_forecast_{region_code}_{forecastPeriod}"
        cached = cache.get(cache_key)
        if cached:
            return Response({"data": cached, "carbon_cast_version": carbon_cast_version}, status=status.HTTP_200_OK)

        from datetime import timedelta
        from django.utils import timezone

        from CarbonCastRESTAPI.models import Forecast168

        forecast_floor = timezone.now() - timedelta(hours=6)  # real ML data refreshes daily, no need for a wide window

        lifecycle_base = Forecast168.objects.filter(
            region_code=region_code,
            emission_factor_type='lifecycle',
            datetime__gte=forecast_floor,
        )
        latest_run = (
            lifecycle_base.exclude(forecast_run_id__isnull=True)
            .exclude(forecast_run_id='')
            .order_by('-issued_at')
            .values_list('forecast_run_id', flat=True)
            .first()
        )
        direct_base = Forecast168.objects.filter(
            region_code=region_code,
            emission_factor_type='direct',
            datetime__gte=forecast_floor,
        )
        if latest_run:
            lifecycle_base = lifecycle_base.filter(forecast_run_id=latest_run)
            direct_base = direct_base.filter(forecast_run_id=latest_run)
        lifecycle_qs = lifecycle_base.order_by('datetime')[:forecastPeriod]
        direct_qs = direct_base.order_by('datetime')[:forecastPeriod]
        final_list = []
        forecast_metadata = None

        if not lifecycle_qs.exists() and not direct_qs.exists():
            # If no forecasts strictly after forecast_floor, retrieve the latest forecast run available for this region
            fallback_run = (
                Forecast168.objects.filter(region_code=region_code)
                .exclude(forecast_run_id__isnull=True)
                .exclude(forecast_run_id='')
                .order_by('-issued_at')
                .values_list('forecast_run_id', flat=True)
                .first()
            )
            if fallback_run:
                lifecycle_qs = Forecast168.objects.filter(
                    region_code=region_code,
                    emission_factor_type='lifecycle',
                    forecast_run_id=fallback_run,
                ).order_by('datetime')[:forecastPeriod]
                direct_qs = Forecast168.objects.filter(
                    region_code=region_code,
                    emission_factor_type='direct',
                    forecast_run_id=fallback_run,
                ).order_by('datetime')[:forecastPeriod]
            else:
                # If no forecast_run_id, get latest Forecast168 rows by datetime
                lifecycle_qs = Forecast168.objects.filter(
                    region_code=region_code,
                    emission_factor_type='lifecycle',
                ).order_by('-datetime')[:forecastPeriod]
                direct_qs = Forecast168.objects.filter(
                    region_code=region_code,
                    emission_factor_type='direct',
                ).order_by('-datetime')[:forecastPeriod]

        if not lifecycle_qs.exists() and not direct_qs.exists():
            final_list = []
            cache.set(cache_key, final_list, 10)
        else:
            lifecycle_list = list(lifecycle_qs)
            direct_list = list(direct_qs)
            count = max(len(lifecycle_list), len(direct_list))
            for i in range(count):
                l = lifecycle_list[i] if i < len(lifecycle_list) else None
                d = direct_list[i] if i < len(direct_list) else None
                primary = l or d
                temp_dict = {
                    field_names[0]: primary.datetime.isoformat() if primary else "",
                    field_names[1]: primary.issued_at.isoformat() if primary and primary.issued_at else "",
                    field_names[2]: primary.provider or "",
                    field_names[3]: region_code,
                    field_names[4]: safe_float(l.value if l else None, 0.0),
                    field_names[5]: safe_float(d.value if d else None, 0.0),
                    field_names[6]: (primary.metric_unit if primary else "gCO2eg/kWh")
                }
                final_list.append(temp_dict)
            cache.set(cache_key, final_list, 10)
        response = {
            "data": final_list,
            "carbon_cast_version": carbon_cast_version
        }
        return Response(response, status=status.HTTP_200_OK)

#6
class CarbonIntensityForecastsHistoryApiView(APIView):
    authentication_classes = authentication_classes
    permission_classes = permission_classes

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter('region_code', openapi.IN_QUERY, description="Region code parameter (e.g., 'AECI').", type=openapi.TYPE_STRING),
            openapi.Parameter('date', openapi.IN_QUERY, description="Date parameter (in the format: 'YYYY-MM-DD').", type=openapi.TYPE_STRING),
            openapi.Parameter('hour', openapi.IN_QUERY, description="Hour parameter (0-23).", type=openapi.TYPE_INTEGER),
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
            
        # Deserialize and validate query parameters
        query_params_serializer = QueryParamsSerializer(data=request.query_params)
        if query_params_serializer.is_valid():
            region_code = query_params_serializer.validated_data.get('region_code')
            print("printing region code", region_code)
            if region_code == 'all':
                regions = US_region_codes
            elif region_code in US_region_codes:
                regions = [region_code]
            else:
                return Response({"error": "Invalid region code parameter"}, status=status.HTTP_400_BAD_REQUEST)
        date = request.query_params.get('date', '')
        hour = request.query_params.get('hour', None)
        print(f"[CarbonIntensityForecastsHistoryApiView] Requested date: {date}, hour: {hour}, Regions: {regions}")

        field_names = [
            "UTC time", "creation_time (UTC)", "version", "region_code", "forecasted_avg_carbon_intensity_lifecycle",
            "forecasted_avg_carbon_intensity_direct", "carbon_intensity_unit"
        ]

        hour_int = None
        if hour is not None:
            try:
                hour_int = int(hour)
                print(f"[DEBUG CI Forecasts History] Hour filter: {hour_int}")
            except (ValueError, TypeError):
                print(f"[DEBUG CI Forecasts History] Invalid hour parameter: {hour}")
                hour_int = None

        try:
            from datetime import datetime
            date_obj = datetime.strptime(date, "%Y-%m-%d").date() if date else None
            print(f"[DEBUG CI Forecasts History] Successfully parsed date: {date_obj}")
        except Exception as e:
            print(f"[DEBUG CI Forecasts History] Failed to parse date '{date}': {e}")
            date_obj = None

        target_date = date_obj if date_obj else datetime.now().date()

        # Cache check
        if region_code == 'all':
            cache_key = f"ci_forecast_history_all_{date}_hour_{hour}"
        else:
            cache_key = f"ci_forecast_history_{region_code}_{date}_hour_{hour}"

        cached = cache.get(cache_key)
        if cached is not None:
            return Response({"data": cached, "carbon_cast_version": carbon_cast_version}, status=status.HTTP_200_OK)

        from CarbonCastRESTAPI.models import Forecast168
        from collections import defaultdict

        from datetime import time as dtime, timezone as dtz
        start_ts = datetime.combine(target_date, dtime.min).replace(tzinfo=dtz.utc)
        end_ts = datetime.combine(target_date, dtime.max).replace(tzinfo=dtz.utc)

        # Fetch forecasts directly and exclusively from Forecast168 database table
        f168_qs = Forecast168.objects.filter(
            region_code__in=regions,
            datetime__range=(start_ts, end_ts),
        )
        if hour_int is not None:
            f168_qs = f168_qs.filter(datetime__hour=hour_int)

        f168_qs = f168_qs.order_by('datetime')

        pairs = defaultdict(dict)
        for row in f168_qs:
            pairs[(row.region_code, row.datetime)][row.emission_factor_type] = row

        final_list = []
        regions_found = set()
        for (reg, dt), types in pairs.items():
            l = types.get('lifecycle')
            d = types.get('direct')
            primary = l or d
            if not primary:
                continue
            temp_dict = {
                field_names[0]: primary.datetime.isoformat(),
                field_names[1]: primary.issued_at.isoformat() if primary and primary.issued_at else "",
                field_names[2]: primary.forecast_run_id or "",
                field_names[3]: reg,
                field_names[4]: safe_float(l.value if l else None, None),
                field_names[5]: safe_float(d.value if d else None, None),
                field_names[6]: (primary.metric_unit if primary else "gCO2eq/kWh") or "gCO2eq/kWh"
            }
            final_list.append(temp_dict)
            regions_found.add(reg)

        cache.set(cache_key, final_list, 15)

        print(f"[DEBUG CI Forecasts History] REGION SUMMARY:")
        print(f"  - Requested regions: {len(regions)}")
        print(f"  - Regions with data in Forecast168: {len(regions_found)}")
        print(f"  - Total forecast items: {len(final_list)}")

        response = {
            "data": final_list,
            "carbon_cast_version": carbon_cast_version
        }
        return Response(response, status=status.HTTP_200_OK)

#7
class EnergySourcesForecastsHistoryApiView(APIView):
    authentication_classes = authentication_classes
    permission_classes = permission_classes

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter('regionCode', openapi.IN_QUERY, description="Region code parameter (e.g., 'AECI').", type=openapi.TYPE_STRING),
            openapi.Parameter('date', openapi.IN_QUERY, description="Date parameter (in the format: 'YYYY-MM-DD').", type=openapi.TYPE_STRING),
            openapi.Parameter('hour', openapi.IN_QUERY, description="Hour parameter (0-23).", type=openapi.TYPE_INTEGER),
            openapi.Parameter('forecastPeriod', openapi.IN_QUERY, description="Forecast period in hours ('24h', '48h', '96h', '168h').", type=openapi.TYPE_STRING, default='24h'),
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

        region_code = request.query_params.get('regionCode', '')
        date = request.query_params.get('date', '')
        hour = request.query_params.get('hour', None)  # Get the hour parameter
        print(f"[EnergySourcesForecastsHistoryApiView] Requested date: {date}, hour: {hour}, Region: {region_code}")
        f = request.query_params.get('forecastPeriod', '24h')
        energy_metadata = None

        f_value = str(f)
        final_interval = int(f_value[:-1] if f_value.endswith('h') else f_value)
        forecastPeriod = int(final_interval)
        
        # Parse date and hour parameters
        try:
            date_obj = datetime.strptime(date, "%Y-%m-%d").date() if date else None
            print(f"[DEBUG EnergySourcesForecastsHistory] Successfully parsed date: {date_obj}")
        except Exception as e:
            print(f"[DEBUG EnergySourcesForecastsHistory] Failed to parse date '{date}': {e}")
            date_obj = datetime.now().date()
            
        hour_int = None
        if hour is not None:
            try:
                hour_int = int(hour)
                print(f"[DEBUG EnergySourcesForecastsHistory] Hour filter: {hour_int}")
            except (ValueError, TypeError):
                print(f"[DEBUG EnergySourcesForecastsHistory] Invalid hour parameter: {hour}")

        # Include hour in cache key when hour parameter is provided
        if hour is not None:
            cache_key = f"energy_forecast_{region_code}_{forecastPeriod}_{date}_hour_{hour}"
        else:
            cache_key = f"energy_forecast_{region_code}_{forecastPeriod}_{date}"
        cached = cache.get(cache_key)
        if cached:
            final_list = cached
        else:
            # try DB queries for energy-type forecasts, filtered by date
            energy_qs = Forecast96.objects.filter(region=region_code, forecast_type__icontains='energy')
            
            # Apply date filter if we have a valid date
            if date_obj:
                energy_qs = energy_qs.filter(ts__date=date_obj)
            
            # Apply hour filter if provided
            if hour_int is not None:
                energy_qs = energy_qs.filter(ts__hour=hour_int)
                print(f"[DEBUG EnergySourcesForecastsHistory] Filtering by hour {hour_int}")
            
            energy_qs = energy_qs.order_by('ts')[:forecastPeriod]
            
            fields = [
                "UTC time", "creation_time (UTC)", "version","region_code", "avg_coal_production_forecast", "avg_nat_gas_production_forecast",
                "avg_nuclear_production_forecast", "avg_oil_production_forecast", "avg_hydro_production_forecast", "avg_solar_production_forecast",
                "avg_wind_production_forecast", "avg_other_production_forecast"
            ]
            final_list = []
            # Initialize metadata
            energy_metadata = None
            
            if energy_qs.exists():
                for obj in energy_qs:
                    temp_dict = {field: "0" for field in fields}
                    temp_dict["UTC time"] = obj.ts.isoformat()
                    temp_dict["creation_time (UTC)"] = obj.data.get("creation_time (UTC)") or obj.data.get("creation_time") or ""
                    temp_dict["version"] = obj.data.get("version") or ""
                    temp_dict["region_code"] = region_code
                    # attempt to map known energy fields from JSON payload
                    for field in fields[4:]:
                        temp_dict[field] = obj.data.get(field, "0")
                    final_list.append(temp_dict)
                cache.set(cache_key, final_list, 10)
            else:
                # fallback to CSV if DB not populated with metadata
                result = get_energy_forecasts_csv_file_with_metadata(region_code, date)
                energy_forecast_csv_file = result["file"]
                energy_metadata = result["metadata"]
                try:
                    with open(energy_forecast_csv_file) as file:
                        lines_csv = file.readlines()
                    energy_forecast_filtered_file = [line.split(',') for i, line in enumerate(lines_csv) if i>0 and i<=forecastPeriod]
                    for i in range(0, len(energy_forecast_filtered_file)):
                        # If hour parameter is specified, filter by hour
                        if hour is not None:
                            try:
                                # Extract hour from CSV timestamp (format: "YYYY-MM-DD HH:MM:SS" or "YYYY-MM-DDTHH:MM:SS")
                                csv_timestamp = energy_forecast_filtered_file[i][0]
                                if 'T' in csv_timestamp:
                                    csv_hour = int(csv_timestamp.split('T')[1].split(':')[0])
                                elif ' ' in csv_timestamp:
                                    csv_hour = int(csv_timestamp.split(' ')[1].split(':')[0])
                                else:
                                    csv_hour = -1  # Invalid format, include the row
                                if csv_hour != hour_int and csv_hour != -1:
                                    continue  # Skip this row if hour doesn't match
                            except (ValueError, IndexError, TypeError):
                                pass  # If can't parse hour, include the row
                        
                        temp_dict = {field: "0" for field in fields}
                        temp_dict["UTC time"] = energy_forecast_filtered_file[i][0]
                        temp_dict["creation_time (UTC)"] = energy_forecast_filtered_file[i][1]
                        temp_dict["version"] = energy_forecast_filtered_file[i][2]
                        temp_dict["region_code"] = region_code
                        splitlines = lines_csv[0].split(",")
                        splitlines[-1] = splitlines[-1].rstrip("\n")
                        for field in fields[4:]:
                            if field in lines_csv[0]:
                                index1 = splitlines.index(field)
                                temp_dict[field] = energy_forecast_filtered_file[i][index1]
                        final_list.append(temp_dict)
                    cache.set(cache_key, final_list, 10)
                except Exception:
                    final_list = []

        response = {
                "data": final_list,
                "carbon_cast_version": carbon_cast_version
            }
        
        # Add metadata if fallback was used
        if energy_metadata and energy_metadata.get("fallback"):
            response["fallback_metadata"] = {
                "message": "Fallback date was used for energy forecast file",
                "requested_date": date,
                "actual_date": energy_metadata.get("actual_date"),
                "fallback": energy_metadata.get("fallback")
            }
            
        # Create response with appropriate headers
        http_response = Response(response, status=status.HTTP_200_OK)
        if energy_metadata and energy_metadata.get("fallback"):
            http_response["X-Fallback-Used"] = "true"
            http_response["X-Actual-Date"] = energy_metadata.get("actual_date", date)
            
        return http_response

#8
