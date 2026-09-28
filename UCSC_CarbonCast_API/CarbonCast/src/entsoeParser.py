import os
import sys
import pandas as pd
from entsoe import EntsoePandasClient

ENTSOE_API_KEY = "3d8580df-94bb-4d1f-9854-50b736a39858"

##########################################################################
# Mapping from ENTSOE fuel names to CarbonCast names
##########################################################################
FUEL_MAP = {
    "Biomass": "BIO",
    "Waste": "BIO",

    "Fossil Brown coal/Lignite": "COAL",
    "Fossil Hard coal": "COAL",
    "Fossil Coal-derived gas": "NG",
    "Fossil Gas": "NG",
    "Fossil Oil": "OIL",
    "Fossil Oil shale": "COAL",
    "Fossil Peat": "COAL",

    "Geothermal": "GEO",

    "Hydro Pumped Storage": "STOR",
    "Hydro Run-of-river and poundage": "HYD",
    "Hydro Water Reservoir": "HYD",

    "Marine": "UNK",

    "Nuclear": "NUC",

    "Other": "UNK",
    "Other renewable": "UNK",

    "Solar": "SOL",

    "Wind Offshore": "WND",
    "Wind Onshore": "WND",

    "Energy storage": "STOR",
}

##########################################################################
# PSR mapping (backup)
##########################################################################

PSR_MAP = {

    "B01":"biomass",
    "B02":"coal",
    "B03":"coal",
    "B04":"nat_gas",
    "B05":"coal",
    "B06":"oil",
    "B07":"oil",
    "B08":"coal",
    "B09":"geothermal",
    "B10":"hydro",
    "B11":"hydro",
    "B12":"hydro",
    "B13":"other",
    "B14":"nuclear",
    "B15":"other",
    "B16":"solar",
    "B17":"other",
    "B18":"wind",
    "B19":"wind",
    "B20":"other",
    "B25":"other",
}
SOURCE_MAP = {
    "BIO": "biomass",
    "COAL": "coal",
    "NG": "nat_gas",
    "OIL": "oil",
    "GEO": "geothermal",
    "HYD": "hydro",
    "NUC": "nuclear",
    "SOL": "solar",
    "WND": "wind",
    "UNK": "other",

    # storage isn't one of your output columns,
    # so map it wherever you want
    "STOR": "hydro",      # recommended
    # or
    # "STOR": "other"
}

##########################################################################
# Area codes
##########################################################################

ENTSOE_AREA_CODES = {
    "AT":"10YAT-APG------L",
    "BE":"10YBE----------2",
    "BG":"10YCA-BULGARIA-R",
    "CH":"10YCH-SWISSGRIDZ",
    "CZ":"10YCZ-CEPS-----N",
    "DE":"10Y1001A1001A83F",
    "DK":"10Y1001A1001A65H",
    "EE":"10Y1001A1001A39I",
    "ES":"10YES-REE------0",
    "FI":"10YFI-1--------U",
    "FR":"10YFR-RTE------C",
    "GR":"10YGR-HTSO-----Y",
    "HR":"10YHR-HEP------M",
    "HU":"10YHU-MAVIR----U",
    "IE":"10YIE-1001A00010",
    "IT":"10YIT-GRTN-----B",
    "LT":"10YLT-1001A0008Q",
    "LV":"10YLV-1001A00074",
    "NL":"10YNL----------L",
    "PL":"10YPL-AREA-----S",
    "PT":"10YPT-REN------W",
    "RO":"10YRO-TEL------P",
    "RS":"10YCS-SERBIATSOV",
    "SE":"10YSE-1--------K",
    "SI":"10YSI-ELES-----O",
    "SK":"10YSK-SEPS-----K",
}

##########################################################################

if len(sys.argv)!=3:
    print("python entsoeParser.py yyyy-mm-dd num_days")
    sys.exit()

start=pd.Timestamp(sys.argv[1],tz="UTC")
end=start+pd.Timedelta(days=int(sys.argv[2]))

client=EntsoePandasClient(api_key=ENTSOE_API_KEY)

os.makedirs("entsoeData",exist_ok=True)

for region,code in ENTSOE_AREA_CODES.items():

    print(region)

    df=client.query_generation(code,start=start,end=end)
    print(df.columns)
    if df is None or len(df)==0:
        continue

    if isinstance(df.columns,pd.MultiIndex):

        print(df.columns)

        try:
            df=df.xs("Actual Aggregated",axis=1,level=1)
        except:
            pass

    df=df.resample("h").mean()

    out=[]

    for ts,row in df.iterrows():

        d={

            "UTC time":ts.strftime("%Y-%m-%d %H:%M"),

            "biomass":0,
            "coal":0,
            "nat_gas":0,
            "geothermal":0,
            "hydro":0,
            "nuclear":0,
            "oil":0,
            "solar":0,
            "wind":0,
            "other":0,
        }

        for col,val in row.items():

            if pd.isna(val):
                continue

            fuel=None

            # MultiIndex column
            if isinstance(col,tuple):

                for x in col:

                    if x in FUEL_MAP:
                        code = FUEL_MAP[x]
                        fuel = SOURCE_MAP.get(code, "other")
                        break
                    if x in PSR_MAP:
                        fuel=PSR_MAP[x]
                        break

            else:

                if col in FUEL_MAP:
                    code = FUEL_MAP[col]
                    fuel = SOURCE_MAP[code]

                elif col in PSR_MAP:
                    fuel=PSR_MAP[col]

            if fuel is None:
                print("UNKNOWN COLUMN:",col)
                fuel="other"

            d[fuel]+=float(val)

        out.append(d)

    new_df = pd.DataFrame(out)

    output_file = f"entsoeData/{region}_clean_mod.csv"

    # ---------------------------------------------------------
    # APPEND TO EXISTING FILE
    # ---------------------------------------------------------
    if os.path.exists(output_file):

        existing_df = pd.read_csv(output_file)

        print(f"Existing rows: {len(existing_df)}")
        print(f"New rows:      {len(new_df)}")

        combined_df = pd.concat(
            [existing_df, new_df],
            ignore_index=True
        )

        # Remove duplicate timestamps
        combined_df = (
            combined_df
            .drop_duplicates(subset=["UTC time"], keep="first")
            .sort_values("UTC time")
            .reset_index(drop=True)
        )

    else:
        combined_df = new_df

    combined_df.to_csv(output_file, index=False)

    print(f"Final rows: {len(combined_df)}")
    print(f"Saved: {output_file}")