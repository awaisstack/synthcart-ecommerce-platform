#!/usr/bin/env python3
"""
gold_layer_dag.py (final: 5 gold tables + dim_reviews)

Creates the following Gold parquet files under gold/<timestamp>/:
 - dim_customers.parquet
 - dim_products.parquet
 - dim_sellers.parquet
 - dim_date.parquet
 - fact_orders.parquet
 - dim_reviews.parquet   <- NEW (contains review_comment_message/title + scores)
"""
from datetime import datetime, timedelta
import io
import os
from typing import List, Optional

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago
from minio import Minio
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# ---------- DAG defaults ----------
DEFAULT_ARGS = {
    "owner": "gold_layer",
    "depends_on_past": False,
    "start_date": days_ago(1),
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

# ---------- Config / env ----------
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_SECURE = os.getenv("MINIO_SECURE", "False").lower() in ("1", "true", "yes")

SILVER_BUCKET = os.getenv("SILVER_BUCKET", "silver")
GOLD_BUCKET = os.getenv("GOLD_BUCKET", "gold")

client = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=MINIO_SECURE)

# ensure gold bucket exists (best-effort)
try:
    if not client.bucket_exists(GOLD_BUCKET):
        client.make_bucket(GOLD_BUCKET)
except Exception as e:
    print("Warning: could not ensure gold bucket exists:", e)

# ---------- Helpers ----------
def list_immediate_subfolders(bucket: str, prefix: str) -> List[str]:
    folders = set()
    for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
        parts = obj.object_name.split("/")
        if len(parts) >= 2 and parts[1]:
            folders.add(parts[1])
    return sorted(folders)

def read_parquet_from_minio(bucket: str, object_name: str) -> pd.DataFrame:
    data = client.get_object(bucket, object_name)
    try:
        raw = data.read()
    finally:
        data.close(); data.release_conn()
    return pd.read_parquet(io.BytesIO(raw), engine="pyarrow")

def write_parquet_to_minio(df: pd.DataFrame, bucket: str, path: str):
    table = pa.Table.from_pandas(df)
    buf = io.BytesIO()
    pq.write_table(table, buf)
    buf.seek(0)
    client.put_object(bucket, path, buf, length=buf.getbuffer().nbytes, content_type="application/octet-stream")

def safe_read_silver(folder: str, name: str, prefix: str = "kaggle") -> Optional[pd.DataFrame]:
    obj = f"{prefix}/{folder}/{name}"
    try:
        return read_parquet_from_minio(SILVER_BUCKET, obj)
    except Exception as e:
        print(f"[safe_read_silver] missing/unreadable {obj}: {e}")
        return None

# ---------- Task implementations ----------
def detect_latest_silver_folders(**context):
    kaggle_folders = list_immediate_subfolders(SILVER_BUCKET, "kaggle/")
    api_folders = list_immediate_subfolders(SILVER_BUCKET, "api/")

    if not kaggle_folders:
        raise RuntimeError("No silver/kaggle/ folders found.")
    if not api_folders:
        raise RuntimeError("No silver/api/ folders found.")

    kaggle_folder = kaggle_folders[-1]
    api_folder = api_folders[-1]
    gold_ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    ti = context["ti"]
    ti.xcom_push(key="kaggle_folder", value=kaggle_folder)
    ti.xcom_push(key="api_folder", value=api_folder)
    ti.xcom_push(key="gold_ts", value=gold_ts)

    print(f"[detect_latest] kaggle_folder={kaggle_folder}, api_folder={api_folder}, gold_ts={gold_ts}")

def build_dim_customers(**context):
    ti = context["ti"]
    kaggle_folder = ti.xcom_pull(key="kaggle_folder", task_ids="detect_latest_silver_folders")
    gold_ts = ti.xcom_pull(key="gold_ts", task_ids="detect_latest_silver_folders")

    customers = safe_read_silver(kaggle_folder, "olist_customers_cleaned.parquet", prefix="kaggle")
    orders = safe_read_silver(kaggle_folder, "olist_orders_cleaned.parquet", prefix="kaggle")
    payments = safe_read_silver(kaggle_folder, "olist_order_payments_cleaned.parquet", prefix="kaggle")
    reviews = safe_read_silver(kaggle_folder, "olist_order_reviews_cleaned.parquet", prefix="kaggle")

    if customers is None:
        raise RuntimeError("olist_customers_cleaned.parquet missing; cannot build dim_customers")

    df = customers.copy()
    df = df.rename(columns={"customer_id": "customer_id", "customer_unique_id": "customer_unique_id", "customer_city": "city", "customer_state": "state"})

    if orders is not None:
        orders_cnt = orders.groupby("customer_id").size().reset_index(name="total_orders")
        df = df.merge(orders_cnt, how="left", on="customer_id")
    else:
        df["total_orders"] = None

    if payments is not None and orders is not None:
        pay_agg = payments.groupby("order_id").agg(order_payment=("payment_value", "sum")).reset_index()
        ords = orders.merge(pay_agg, how="left", on="order_id")
        cust_pay = ords.groupby("customer_id").agg(avg_payment_value=("order_payment", "mean")).reset_index()
        df = df.merge(cust_pay, how="left", on="customer_id")
    else:
        df["avg_payment_value"] = None

    if reviews is not None and orders is not None:
        revs = reviews.merge(orders[["order_id", "customer_id"]], how="left", on="order_id")
        cust_rev = revs.groupby("customer_id").agg(avg_review_score=("review_score", "mean")).reset_index()
        df = df.merge(cust_rev, how="left", on="customer_id")
    else:
        df["avg_review_score"] = None

    dim_customers = df[["customer_id", "customer_unique_id", "city", "state", "total_orders", "avg_payment_value", "avg_review_score"]].copy()

    out_path = f"gold/{gold_ts}/dim_customers.parquet"
    write_parquet_to_minio(dim_customers, GOLD_BUCKET, out_path)
    print("[build_dim_customers] wrote", out_path)

def build_dim_products(**context):
    ti = context["ti"]
    kaggle_folder = ti.xcom_pull(key="kaggle_folder", task_ids="detect_latest_silver_folders")
    api_folder = ti.xcom_pull(key="api_folder", task_ids="detect_latest_silver_folders")
    gold_ts = ti.xcom_pull(key="gold_ts", task_ids="detect_latest_silver_folders")

    products = safe_read_silver(kaggle_folder, "olist_products_cleaned.parquet", prefix="kaggle")
    api_products = safe_read_silver(api_folder, "api_products_cleaned.parquet", prefix="api")
    translation = safe_read_silver(kaggle_folder, "product_category_name_translation_cleaned.parquet", prefix="kaggle")
    order_items = safe_read_silver(kaggle_folder, "olist_order_items_cleaned.parquet", prefix="kaggle")
    reviews = safe_read_silver(kaggle_folder, "olist_order_reviews_cleaned.parquet", prefix="kaggle")

    rows = []
    trans_map = {}
    if translation is not None:
        trans_map = translation.set_index("product_category_name")["product_category_name_english"].to_dict()

    if products is not None:
        p = products.copy()
        p["product_category_name_english"] = p.get("product_category_name").map(trans_map).fillna("unknown")
        dim_p = p[["product_id", "product_category_name", "product_category_name_english", "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm"]].copy()
        rows.append(dim_p)

    if api_products is not None:
        ap = api_products.copy()
        ap_dim = ap[["api_product_id", "title", "category", "price", "rating", "stock", "brand"]].copy()
        ap_dim = ap_dim.rename(columns={"api_product_id": "product_key", "title": "title", "category": "category_api"})
        rows.append(ap_dim)

    # Build combined dim_products; then compute avg_rating per product_id (via reviews->order_items)
    if rows:
        dim_products = pd.concat(rows, ignore_index=True, sort=False)
    else:
        dim_products = pd.DataFrame()

    # ---- compute avg_rating per product_id using reviews + order_items (if available) ----
    if reviews is not None and order_items is not None:
        # ensure numeric review_score
        reviews["review_score"] = pd.to_numeric(reviews.get("review_score"), errors="coerce")
        # join reviews to order_items on order_id, then group by product_id
        rev_oi = reviews.merge(order_items[["order_id", "product_id"]], how="left", on="order_id")
        prod_rating = rev_oi.groupby("product_id").agg(avg_rating=("review_score", "mean")).reset_index()
        # left-join into dim_products where product_id exists
        if "product_id" in dim_products.columns:
            dim_products = dim_products.merge(prod_rating, how="left", on="product_id")
        else:
            # add avg_rating column if missing product_id mapping
            dim_products = dim_products.assign(avg_rating=pd.NA)
    else:
        if "avg_rating" not in dim_products.columns:
            dim_products["avg_rating"] = pd.NA

    out_path = f"gold/{gold_ts}/dim_products.parquet"
    write_parquet_to_minio(dim_products, GOLD_BUCKET, out_path)
    print("[build_dim_products] wrote", out_path)

def build_dim_sellers(**context):
    ti = context["ti"]
    kaggle_folder = ti.xcom_pull(key="kaggle_folder", task_ids="detect_latest_silver_folders")
    gold_ts = ti.xcom_pull(key="gold_ts", task_ids="detect_latest_silver_folders")

    sellers = safe_read_silver(kaggle_folder, "olist_sellers_cleaned.parquet", prefix="kaggle")
    if sellers is None:
        raise RuntimeError("olist_sellers_cleaned.parquet missing; cannot build dim_sellers")

    df = sellers.copy()
    dim_sellers = df[["seller_id", "seller_city", "seller_state"]].rename(columns={"seller_city": "city", "seller_state": "state"}).copy()

    out_path = f"gold/{gold_ts}/dim_sellers.parquet"
    write_parquet_to_minio(dim_sellers, GOLD_BUCKET, out_path)
    print("[build_dim_sellers] wrote", out_path)

def build_dim_date(**context):
    ti = context["ti"]
    kaggle_folder = ti.xcom_pull(key="kaggle_folder", task_ids="detect_latest_silver_folders")
    gold_ts = ti.xcom_pull(key="gold_ts", task_ids="detect_latest_silver_folders")

    orders = safe_read_silver(kaggle_folder, "olist_orders_cleaned.parquet", prefix="kaggle")
    if orders is None:
        raise RuntimeError("olist_orders_cleaned.parquet missing; cannot build dim_date")

    dates = pd.to_datetime(orders["order_purchase_timestamp"], errors="coerce").dt.normalize().dropna().unique()
    dates = sorted(list(pd.to_datetime(dates)))

    rows = []
    for d in dates:
        rows.append({
            "date_key": int(d.strftime("%Y%m%d")),
            "date": d.date().isoformat(),
            "year": d.year,
            "month": d.month,
            "day": d.day,
            "weekday": d.weekday(),
            "is_weekend": d.weekday() >= 5,
        })

    dim_date = pd.DataFrame(rows)
    out_path = f"gold/{gold_ts}/dim_date.parquet"
    write_parquet_to_minio(dim_date, GOLD_BUCKET, out_path)
    print("[build_dim_date] wrote", out_path)

def build_dim_reviews(**context):
    """NEW: write review comments and scores as a gold table for DA word-frequency & review KPIs"""
    ti = context["ti"]
    kaggle_folder = ti.xcom_pull(key="kaggle_folder", task_ids="detect_latest_silver_folders")
    gold_ts = ti.xcom_pull(key="gold_ts", task_ids="detect_latest_silver_folders")

    reviews = safe_read_silver(kaggle_folder, "olist_order_reviews_cleaned.parquet", prefix="kaggle")
    if reviews is None:
        print("[build_dim_reviews] no reviews found; writing empty df")
        dim_reviews = pd.DataFrame(columns=["review_id","order_id","review_score","review_comment_title","review_comment_message","review_creation_date"])
    else:
        rev = reviews.copy()
        # keep textual fields for word-frequency analysis
        dim_reviews = rev[["review_id","order_id","review_score","review_comment_title","review_comment_message","review_creation_date"]].copy()

    out_path = f"gold/{gold_ts}/dim_reviews.parquet"
    write_parquet_to_minio(dim_reviews, GOLD_BUCKET, out_path)
    print("[build_dim_reviews] wrote", out_path)

def build_fact_orders(**context):
    ti = context["ti"]
    kaggle_folder = ti.xcom_pull(key="kaggle_folder", task_ids="detect_latest_silver_folders")
    gold_ts = ti.xcom_pull(key="gold_ts", task_ids="detect_latest_silver_folders")

    orders = safe_read_silver(kaggle_folder, "olist_orders_cleaned.parquet", prefix="kaggle")
    order_items = safe_read_silver(kaggle_folder, "olist_order_items_cleaned.parquet", prefix="kaggle")
    payments = safe_read_silver(kaggle_folder, "olist_order_payments_cleaned.parquet", prefix="kaggle")
    customers = safe_read_silver(kaggle_folder, "olist_customers_cleaned.parquet", prefix="kaggle")
    sellers = safe_read_silver(kaggle_folder, "olist_sellers_cleaned.parquet", prefix="kaggle")
    reviews = safe_read_silver(kaggle_folder, "olist_order_reviews_cleaned.parquet", prefix="kaggle")

    if orders is None or order_items is None:
        raise RuntimeError("orders/order_items missing; cannot build fact_orders")

    oi = order_items.copy()
    # join orders to get customer and timestamps and estimated delivery
    orders_subset = orders[["order_id", "customer_id", "order_purchase_timestamp", "order_delivered_customer_date", "order_status", "order_estimated_delivery_date"]]
    oi = oi.merge(orders_subset, how="left", on="order_id")

    oi["price"] = pd.to_numeric(oi.get("price"), errors="coerce")
    oi["freight_value"] = pd.to_numeric(oi.get("freight_value"), errors="coerce")

    # aggregate payments per order -> total_payment + avg_installments + mode(payment_type)
    if payments is not None:
        pay = payments.copy()
        pay["payment_installments"] = pd.to_numeric(pay.get("payment_installments"), errors="coerce")
        pay_agg_sum = pay.groupby("order_id").agg(total_payment=("payment_value", "sum")).reset_index()
        pay_agg_inst = pay.groupby("order_id").agg(payment_installments_avg=("payment_installments", "mean")).reset_index()
        # payment_type_mode: pick the mode; fall back to first non-null if mode empty
        def mode_or_first(s):
            try:
                m = s.mode(dropna=True)
                if not m.empty:
                    return m.iloc[0]
                # else return first non-null
                v = s.dropna()
                return v.iloc[0] if len(v)>0 else pd.NA
            except Exception:
                return pd.NA
        pay_mode = pay.groupby("order_id").agg(payment_type_mode=("payment_type", lambda s: mode_or_first(s))).reset_index()
        # merge aggregated payment info into oi
        oi = oi.merge(pay_agg_sum, how="left", on="order_id")
        oi = oi.merge(pay_agg_inst, how="left", on="order_id")
        oi = oi.merge(pay_mode, how="left", on="order_id")
    else:
        oi["total_payment"] = None
        oi["payment_installments_avg"] = None
        oi["payment_type_mode"] = None

    # compute revenue and date_key
    oi["revenue"] = oi["price"].fillna(0) + oi["freight_value"].fillna(0)
    oi["order_purchase_dt"] = pd.to_datetime(oi["order_purchase_timestamp"], errors="coerce")
    oi["date_key"] = oi["order_purchase_dt"].dt.strftime("%Y%m%d").astype(float).astype("Int64")

    # delivery_days and on_time flag (compare delivered vs estimated)
    try:
        oi["delivered_dt"] = pd.to_datetime(oi["order_delivered_customer_date"], errors="coerce")
        oi["estimated_dt"] = pd.to_datetime(oi["order_estimated_delivery_date"], errors="coerce")
        oi["delivery_days"] = (oi["delivered_dt"] - oi["order_purchase_dt"]).dt.days
        # on_time: True if delivered_dt <= estimated_dt (if both present)
        oi["on_time"] = None
        mask = oi["delivered_dt"].notna() & oi["estimated_dt"].notna()
        oi.loc[mask, "on_time"] = (oi.loc[mask, "delivered_dt"] <= oi.loc[mask, "estimated_dt"])
    except Exception:
        oi["delivery_days"] = None
        oi["on_time"] = None

    # attach FK lookups (customers/sellers)
    if customers is not None:
        oi = oi.merge(customers[["customer_id", "customer_unique_id"]], how="left", on="customer_id")
    else:
        oi["customer_unique_id"] = None

    if sellers is not None:
        oi = oi.merge(sellers[["seller_id", "seller_state"]], how="left", on="seller_id")
    else:
        oi["seller_state"] = None

    # Provide review text count / score at order level optionally (not required)
    # (we already created dim_reviews; DA can use that for text analysis)

    # produce fact_orders at order_item granularity with FKs and metrics
    fact_orders = oi[[
        "order_id", "order_item_id", "date_key", "customer_id", "customer_unique_id",
        "product_id", "seller_id", "seller_state", "order_status",
        "price", "freight_value", "revenue", "total_payment", "payment_installments_avg", "payment_type_mode",
        "delivery_days", "on_time", "order_estimated_delivery_date"
    ]].copy()

    out_path = f"gold/{gold_ts}/fact_orders.parquet"
    write_parquet_to_minio(fact_orders, GOLD_BUCKET, out_path)
    print("[build_fact_orders] wrote", out_path)

def finalize(**context):
    ti = context["ti"]
    gold_ts = ti.xcom_pull(key="gold_ts", task_ids="detect_latest_silver_folders")
    print(f"[finalize] gold run complete. gold/{gold_ts}/ contains dim & fact parquet files.")

# ---------- DAG ----------
with DAG(
    dag_id="gold_layer_dag",
    default_args=DEFAULT_ARGS,
    description="Gold Layer - dims & fact tables",
    schedule_interval=None,
    catchup=False,
    max_active_runs=1,
    tags=["gold", "aggregation", "synthcart"],
) as dag:

    t_detect = PythonOperator(
        task_id="detect_latest_silver_folders",
        python_callable=detect_latest_silver_folders,
        provide_context=True,
    )

    t_dim_customers = PythonOperator(
        task_id="build_dim_customers",
        python_callable=build_dim_customers,
        provide_context=True,
    )

    t_dim_products = PythonOperator(
        task_id="build_dim_products",
        python_callable=build_dim_products,
        provide_context=True,
    )

    t_dim_sellers = PythonOperator(
        task_id="build_dim_sellers",
        python_callable=build_dim_sellers,
        provide_context=True,
    )

    t_dim_date = PythonOperator(
        task_id="build_dim_date",
        python_callable=build_dim_date,
        provide_context=True,
    )

    # NEW reviews task (run in parallel with dims)
    t_dim_reviews = PythonOperator(
        task_id="build_dim_reviews",
        python_callable=build_dim_reviews,
        provide_context=True,
    )

    t_fact_orders = PythonOperator(
        task_id="build_fact_orders",
        python_callable=build_fact_orders,
        provide_context=True,
    )

    t_finalize = PythonOperator(
        task_id="finalize",
        python_callable=finalize,
        provide_context=True,
    )

    # graph: detect -> build dims/date/reviews in parallel -> fact -> finalize
    t_detect >> [t_dim_customers, t_dim_products, t_dim_sellers, t_dim_date, t_dim_reviews] >> t_fact_orders >> t_finalize
