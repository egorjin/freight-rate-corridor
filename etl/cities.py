import pandas as pd


def split_place(full_name):
    """'Казань, Республика Татарстан' -> ('Казань', 'Республика Татарстан')."""
    if full_name is None:
        return None, None
    city, sep, region = str(full_name).partition(",")
    city = city.strip()
    region = region.strip()
    if not sep:
        return city or None, None
    return city or None, region or None


def dedup_cities(df):
    """gc_id is not unique. Keep the row with the smallest cities.id."""
    ordered = df.sort_values(["gc_id", "id"], kind="mergesort")
    kept = ordered.drop_duplicates("gc_id", keep="first").copy()
    parsed = kept["full_name_local"].map(split_place)
    kept["city_name"] = [item[0] for item in parsed]
    kept["region_name"] = [item[1] for item in parsed]
    kept = kept.rename(columns={"id": "city_id"})
    return kept.reset_index(drop=True)
