#!/usr/bin/env python3
"""
silver_cleaning.py - final merged version

- Uses latest_paths.txt (if present) to pick the Kaggle folder (keeps Airflow sync).
- Detects the two newest api_data/ folders and processes products.json + users.json from them.
- Cleans all 9 Kaggle CSVs + API products/users, masks PII, flattens addresses, writes Parquet to silver/.
- Robust CSV reading, column validation, per-file error handling and logging.
"""

import os
import io
import json
from datetime import datetime
from typing import List, Optional, Tuple

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from minio import Minio

# -----------------------
# Config / env
# -----------------------
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_SECURE = os.getenv("MINIO_SECURE", "False").lower() in ("1", "true", "yes")

BRONZE_BUCKET = os.getenv("BRONZE_BUCKET", "bronze")
SILVER_BUCKET = os.getenv("SILVER_BUCKET", "silver")
LATEST_PATHS_FILE = "/opt/airflow/tmp/latest_paths.txt"  # written by DAG's get_latest_bronze_folders

TMP_DIR = os.getenv("TMP_DIR", "/tmp/bronze_processing")
os.makedirs(TMP_DIR, exist_ok=True)

client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE,
)

# Ensure silver bucket exists
try:
    if not client.bucket_exists(SILVER_BUCKET):
        client.make_bucket(SILVER_BUCKET)
except Exception as exc:
    print("Warning: could not ensure silver bucket exists:", exc)


# -----------------------
# Helpers
# -----------------------
def read_latest_paths_from_file() -> Tuple[Optional[str], Optional[str]]:
    """Return (kaggle_folder, api_folder) if the DAG wrote them; else (None, None)."""
    if os.path.exists(LATEST_PATHS_FILE):
        try:
            with open(LATEST_PATHS_FILE, "r") as f:
                content = f.read().strip()
            kaggle_folder, api_folder = content.split(",")
            kaggle_folder = kaggle_folder.strip() or None
            api_folder = api_folder.strip() or None
            return kaggle_folder, api_folder
        except Exception as e:
            print("Info: failed to read latest_paths.txt:", e)
            return None, None
    return None, None


def list_immediate_subfolders(prefix: str) -> List[str]:
    """List immediate subfolder names under a prefix like 'api_data/' or 'kaggle_data/'."""
    folders = set()
    for obj in client.list_objects(BRONZE_BUCKET, prefix=prefix, recursive=True):
        parts = obj.object_name.split("/")
        if len(parts) >= 2 and parts[1]:
            folders.add(parts[1])
    return sorted(folders)


def detect_latest_kaggle_folder(kaggle_from_file: Optional[str]) -> str:
    """Prefer kaggle_from_file if provided and present; else detect latest by listing."""
    if kaggle_from_file:
        folders = list_immediate_subfolders("kaggle_data/")
        if kaggle_from_file in folders:
            return kaggle_from_file
        else:
            print(f"Info: kaggle folder from file ({kaggle_from_file}) not found in MinIO; falling back to latest.")
    folders = list_immediate_subfolders("kaggle_data/")
    if not folders:
        raise RuntimeError("No kaggle_data subfolders found in bronze bucket.")
    return folders[-1]


def detect_two_latest_api_folders(api_from_file: Optional[str]) -> List[str]:
    """
    Return the two latest api_data folders (names).
    If api_from_file provided and present, ensure it is included (but still prefer latest two overall).
    """
    folders = list_immediate_subfolders("api_data/")
    if not folders:
        raise RuntimeError("No api_data subfolders found in bronze bucket.")
    # pick the last two
    if len(folders) >= 2:
        chosen = folders[-2:]
    else:
        chosen = folders[:]
    # if api_from_file specified but not in chosen, try to include it (best-effort)
    if api_from_file and api_from_file not in chosen and api_from_file in folders:
        chosen = sorted(set(chosen + [api_from_file]))
        chosen = sorted(chosen)[-2:]
    return chosen


def read_remote_bytes(bucket: str, obj_name: str) -> bytes:
    """Download object bytes from MinIO (raises on error)."""
    data = client.get_object(bucket, obj_name)
    try:
        raw = data.read()
    finally:
        data.close()
        data.release_conn()
    return raw


def safe_read_csv_bytes(raw_bytes: bytes) -> pd.DataFrame:
    """Try several separators and encoding fallback to robustly read a CSV-like file."""
    for sep in (",", "\t", ";"):
        try:
            df = pd.read_csv(io.BytesIO(raw_bytes), sep=sep, engine="python", encoding="utf-8")
            if df.shape[1] > 1:
                return df
        except Exception:
            pass
    # final fallback: try latin-1
    try:
        return pd.read_csv(io.BytesIO(raw_bytes), engine="python", encoding="latin-1")
    except Exception as e:
        raise RuntimeError(f"Failed to parse CSV bytes: {e}")


def upload_parquet_df(df: pd.DataFrame, object_path: str):
    """Write pandas DataFrame to Parquet in MinIO."""
    table = pa.Table.from_pandas(df)
    buf = io.BytesIO()
    pq.write_table(table, buf)
    buf.seek(0)
    client.put_object(SILVER_BUCKET, object_path, buf, length=buf.getbuffer().nbytes, content_type="application/octet-stream")


# -----------------------
# Cleaning helpers (common)
# -----------------------
def lowercase_and_normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    # convert 'nan' strings to actual NA and trim text
    for c in df.select_dtypes(include="object").columns:
        df[c] = df[c].astype(str).str.strip().replace({"nan": pd.NA})
    return df


def parse_dates_column(col_series: pd.Series) -> pd.Series:
    # do not use deprecated infer_datetime_format argument
    return pd.to_datetime(col_series, errors="coerce")


# -----------------------
# Cleaning functions (per dataset)
# -----------------------
def clean_customers(df: pd.DataFrame) -> pd.DataFrame:
    df = lowercase_and_normalize_columns(df)
    expected = ["customer_id", "customer_unique_id", "customer_zip_code_prefix", "customer_city", "customer_state"]
    for c in expected:
        if c not in df.columns:
            df[c] = pd.NA
    df["customer_zip_code_prefix"] = pd.to_numeric(df["customer_zip_code_prefix"], errors="coerce").astype("Int64")
    df["customer_city"] = df["customer_city"].fillna("unknown").str.title()
    df["customer_state"] = df["customer_state"].fillna("unknown").str.upper()
    df = df.dropna(subset=["customer_id"]).drop_duplicates(subset=["customer_id"])
    return df[expected]


def clean_products(df: pd.DataFrame) -> pd.DataFrame:
    df = lowercase_and_normalize_columns(df)
    expected = [
        "product_id", "product_category_name", "product_name_lenght", "product_description_lenght",
        "product_photos_qty", "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm"
    ]
    for c in expected:
        if c not in df.columns:
            df[c] = pd.NA
    numcols = [c for c in expected if c not in ("product_id", "product_category_name")]
    for c in numcols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["product_category_name"] = df["product_category_name"].fillna("unknown_category")
    df = df.dropna(subset=["product_id"]).drop_duplicates(subset=["product_id"])
    return df[expected]


def clean_sellers(df: pd.DataFrame) -> pd.DataFrame:
    df = lowercase_and_normalize_columns(df)
    expected = ["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"]
    for c in expected:
        if c not in df.columns:
            df[c] = pd.NA
    df["seller_zip_code_prefix"] = pd.to_numeric(df["seller_zip_code_prefix"], errors="coerce").astype("Int64")
    df["seller_city"] = df["seller_city"].fillna("unknown").str.title()
    df["seller_state"] = df["seller_state"].fillna("unknown").str.upper()
    df = df.dropna(subset=["seller_id"]).drop_duplicates(subset=["seller_id"])
    return df[expected]


def clean_orders(df: pd.DataFrame) -> pd.DataFrame:
    df = lowercase_and_normalize_columns(df)
    expected = [
        "order_id", "customer_id", "order_status", "order_purchase_timestamp", "order_approved_at",
        "order_delivered_carrier_date", "order_delivered_customer_date", "order_estimated_delivery_date"
    ]
    for c in expected:
        if c not in df.columns:
            df[c] = pd.NA
    for dt_col in ["order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
                   "order_delivered_customer_date", "order_estimated_delivery_date"]:
        df[dt_col] = parse_dates_column(df[dt_col])
    df["order_status"] = df["order_status"].fillna("unknown").str.lower()
    df = df.dropna(subset=["order_id"]).drop_duplicates(subset=["order_id"])
    return df[expected]


def clean_order_items(df: pd.DataFrame) -> pd.DataFrame:
    df = lowercase_and_normalize_columns(df)
    expected = ["order_id", "order_item_id", "product_id", "seller_id", "shipping_limit_date", "price", "freight_value"]
    for c in expected:
        if c not in df.columns:
            df[c] = pd.NA
    df["shipping_limit_date"] = parse_dates_column(df["shipping_limit_date"])
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["freight_value"] = pd.to_numeric(df["freight_value"], errors="coerce")
    df = df.dropna(subset=["order_id", "order_item_id"]).drop_duplicates(subset=["order_id", "order_item_id"])
    return df[expected]


def clean_payments(df: pd.DataFrame) -> pd.DataFrame:
    df = lowercase_and_normalize_columns(df)
    expected = ["order_id", "payment_sequential", "payment_type", "payment_installments", "payment_value"]
    for c in expected:
        if c not in df.columns:
            df[c] = pd.NA
    df["payment_installments"] = pd.to_numeric(df["payment_installments"], errors="coerce").astype("Int64")
    df["payment_value"] = pd.to_numeric(df["payment_value"], errors="coerce")
    df["payment_type"] = df["payment_type"].fillna("other").str.lower()
    df = df.dropna(subset=["order_id", "payment_sequential"]).drop_duplicates(subset=["order_id", "payment_sequential"])
    return df[expected]


def clean_reviews(df: pd.DataFrame) -> pd.DataFrame:
    df = lowercase_and_normalize_columns(df)
    expected = [
        "review_id", "order_id", "review_score", "review_comment_title",
        "review_comment_message", "review_creation_date", "review_answer_timestamp"
    ]
    for c in expected:
        if c not in df.columns:
            df[c] = pd.NA
    df["review_score"] = pd.to_numeric(df["review_score"], errors="coerce").astype("Int64")
    df["review_creation_date"] = parse_dates_column(df["review_creation_date"])
    df["review_answer_timestamp"] = parse_dates_column(df["review_answer_timestamp"])
    df["review_comment_title"] = df["review_comment_title"].fillna("").astype(str)
    df["review_comment_message"] = df["review_comment_message"].fillna("").astype(str)
    df = df.dropna(subset=["review_id"]).drop_duplicates(subset=["review_id"])
    return df[expected]


def clean_geolocation(df: pd.DataFrame) -> pd.DataFrame:
    df = lowercase_and_normalize_columns(df)
    expected = [
        "geolocation_zip_code_prefix", "geolocation_lat", "geolocation_lng",
        "geolocation_city", "geolocation_state"
    ]
    for c in expected:
        if c not in df.columns:
            df[c] = pd.NA
    df["geolocation_zip_code_prefix"] = pd.to_numeric(df["geolocation_zip_code_prefix"], errors="coerce").astype("Int64")
    df["geolocation_lat"] = pd.to_numeric(df["geolocation_lat"], errors="coerce")
    df["geolocation_lng"] = pd.to_numeric(df["geolocation_lng"], errors="coerce")
    df["geolocation_city"] = df["geolocation_city"].fillna("unknown").str.title()
    df["geolocation_state"] = df["geolocation_state"].fillna("unknown").str.upper()
    df = df.drop_duplicates()
    return df[expected]


def clean_category_translation(df: pd.DataFrame) -> pd.DataFrame:
    df = lowercase_and_normalize_columns(df)
    expected = ["product_category_name", "product_category_name_english"]
    for c in expected:
        if c not in df.columns:
            df[c] = pd.NA
    df["product_category_name"] = df["product_category_name"].fillna("unknown_category")
    df["product_category_name_english"] = df["product_category_name_english"].fillna("unknown")
    df = df.drop_duplicates(subset=["product_category_name"])
    return df[expected]


# -----------------------
# API cleaning & PII
# -----------------------
def clean_api_products(df: pd.DataFrame) -> pd.DataFrame:
    df = lowercase_and_normalize_columns(df)
    # if id exists rename to api_product_id to avoid clashes
    if "id" in df.columns and "api_product_id" not in df.columns:
        df = df.rename(columns={"id": "api_product_id"})
    expected = ["api_product_id", "title", "description", "category", "price", "rating", "stock", "brand", "thumbnail"]
    for c in expected:
        if c not in df.columns:
            df[c] = pd.NA
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")
    df = df.drop_duplicates(subset=["api_product_id"])
    return df[expected]


def flatten_address_field(addr):
    """Try to flatten nested address dict into simple fields (safe)."""
    if not isinstance(addr, dict):
        return pd.NA, pd.NA, pd.NA
    city = addr.get("city") or addr.get("town") or addr.get("municipality") or pd.NA
    state = addr.get("state") or addr.get("stateCode") or addr.get("statecode") or pd.NA
    country = addr.get("country") or pd.NA
    return city, state, country


def clean_api_users(df: pd.DataFrame) -> pd.DataFrame:
    df = lowercase_and_normalize_columns(df)
    # drop obviously sensitive fields if present
    sensitive = ["password", "ssn", "bank", "cardnumber", "card_number", "iban", "crypto", "wallet"]
    for c in sensitive:
        if c in df.columns:
            df = df.drop(columns=[c], errors="ignore")
    # mask email
    if "email" in df.columns:
        df["email_masked"] = df["email"].astype(str).apply(lambda x: (x.split("@")[0][:1] + "***@" + x.split("@")[-1]) if "@" in x else pd.NA)
    # flatten address if nested
    city_series = []
    state_series = []
    country_series = []
    addr_column = df["address"] if "address" in df.columns else pd.Series([pd.NA] * len(df))
    for a in addr_column:
        cty, st, cn = flatten_address_field(a)
        city_series.append(cty)
        state_series.append(st)
        country_series.append(cn)
    out = pd.DataFrame({
        "user_id": df["id"] if "id" in df.columns else df.get("user_id", pd.Series([pd.NA] * len(df))),
        "first_name": df.get("firstname") if "firstname" in df.columns else df.get("first_name"),
        "last_name": df.get("lastname") if "lastname" in df.columns else df.get("last_name"),
        "username": df.get("username"),
        "email_masked": df.get("email_masked") if "email_masked" in df.columns else pd.NA,
        "city": pd.Series(city_series),
        "state": pd.Series(state_series),
        "country": pd.Series(country_series),
    })
    out = out.where(pd.notna(out), None)  # stabilize null types
    out = out.dropna(subset=["user_id"]).drop_duplicates(subset=["user_id"])
    return out


# -----------------------
# Main process
# -----------------------
def process():
    # read latest paths file (if DAG produced it)
    kaggle_from_file, api_from_file = read_latest_paths_from_file()

    kaggle_folder = detect_latest_kaggle_folder(kaggle_from_file)
    api_folders = detect_two_latest_api_folders(api_from_file)  # list of 1 or 2

    print("Selected kaggle folder:", kaggle_folder)
    print("Selected api folders:", api_folders)

    # create output prefixes that map to the bronze origin (helps tracing back)
    out_kaggle_prefix = f"kaggle/{kaggle_folder}/"
    api_prefix_name = "_".join(api_folders)
    out_api_prefix = f"api/{api_prefix_name}/"

    # mapping of expected kaggle filenames -> cleaner and output name
    kaggle_mapping = {
        "olist_customers_dataset.csv": ("olist_customers_cleaned.parquet", clean_customers),
        "olist_products_dataset.csv": ("olist_products_cleaned.parquet", clean_products),
        "olist_sellers_dataset.csv": ("olist_sellers_cleaned.parquet", clean_sellers),
        "olist_orders_dataset.csv": ("olist_orders_cleaned.parquet", clean_orders),
        "olist_order_items_dataset.csv": ("olist_order_items_cleaned.parquet", clean_order_items),
        "olist_order_payments_dataset.csv": ("olist_order_payments_cleaned.parquet", clean_payments),
        "olist_order_reviews_dataset.csv": ("olist_order_reviews_cleaned.parquet", clean_reviews),
        "olist_geolocation_dataset.csv": ("olist_geolocation_cleaned.parquet", clean_geolocation),
        "product_category_name_translation.csv": ("product_category_name_translation_cleaned.parquet", clean_category_translation),
    }

    # Process Kaggle CSVs
    for fname, (outfname, cleaner) in kaggle_mapping.items():
        bronze_obj = f"kaggle_data/{kaggle_folder}/{fname}"
        try:
            print(f"Attempting download: {bronze_obj}")
            raw = read_remote_bytes(BRONZE_BUCKET, bronze_obj)
            df = safe_read_csv_bytes(raw)
            cleaned = cleaner(df)
            silver_obj = f"{out_kaggle_prefix}{outfname}"
            print(f"Uploading cleaned parquet to silver/{silver_obj} ...")
            upload_parquet_df(cleaned, silver_obj)
            print("Uploaded:", silver_obj)
        except Exception as e:
            print(f"Warning: failed processing {bronze_obj}: {e}")

    # Process API files: iterate the two selected API folders and try products/users
    for fldr in api_folders:
        for file_name, cleaner, outname in [
            ("products.json", clean_api_products, "api_products_cleaned.parquet"),
            ("users.json", clean_api_users, "api_users_cleaned.parquet"),
        ]:
            bronze_obj = f"api_data/{fldr}/{file_name}"
            try:
                print(f"Attempting download: {bronze_obj}")
                raw = read_remote_bytes(BRONZE_BUCKET, bronze_obj)
                jd = json.loads(raw.decode("utf-8"))
                # some API JSONs have {"products": [...]} while some are raw lists
                key = file_name.split(".")[0]
                data_list = jd.get(key) if isinstance(jd, dict) and key in jd else jd
                df = pd.json_normalize(data_list)
                cleaned = cleaner(df)
                silver_obj = f"{out_api_prefix}{outname}"
                print(f"Uploading cleaned API parquet to silver/{silver_obj} ...")
                upload_parquet_df(cleaned, silver_obj)
                print("Uploaded:", silver_obj)
            except Exception as e:
                # some api folders won't have both files; skip with info
                print(f"Info: skipped {bronze_obj} (missing/failed): {e}")

    print("Silver cleaning finished successfully.")


if __name__ == "__main__":
    process()
