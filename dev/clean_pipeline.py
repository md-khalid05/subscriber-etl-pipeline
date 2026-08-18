import ast
import json
import logging
import os
import sqlite3
import time
import pandas as pd

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("pipeline.log"), logging.StreamHandler()],
)


def safe_parse(x):
    """Safely parse JSON or stringified dicts into native Python dictionaries."""
    if pd.isna(x):
        return {}
    if isinstance(x, dict):
        return x
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:
            try:
                return ast.literal_eval(x)
            except Exception:
                return {}
    return {}


def run_pipeline(
    input_db: str = "cademycode.db",
    output_db: str = "cademy_cleansed.db",
    output_csv: str = "cademycode_cleansed.csv",
):
    start_time = time.time()
    logging.info("Starting CademyCode Data Pipeline...")

    # 1. Validation: Check input file existence
    if not os.path.exists(input_db):
        logging.error(f"Input database file '{input_db}' not found.")
        raise FileNotFoundError(f"Database {input_db} does not exist.")

    # 2. Extract
    logging.info(f"Extracting raw tables from {input_db}...")
    with sqlite3.connect(input_db) as conn:
        student_raw = pd.read_sql_query("SELECT * FROM cademycode_students", conn)
        courses_raw = pd.read_sql_query("SELECT * FROM cademycode_courses", conn)
        jobs_raw = pd.read_sql_query(
            "SELECT * FROM cademycode_student_jobs", conn
        )

    logging.info(
        f"Raw data extracted: students={len(student_raw)}, courses={len(courses_raw)}, jobs={len(jobs_raw)}"
    )

    # 3. Transform: Calculate Age and Age Groups
    logging.info("Calculating age and age groups...")
    now = pd.Timestamp.now()
    student_raw["dob"] = pd.to_datetime(student_raw["dob"])
    student_raw["age"] = (now - student_raw["dob"]).dt.days // 365.25
    student_raw["age_group"] = (student_raw["age"] // 10) * 10

    # 4. Transform: Unpack JSON Contact Info & Split Address
    logging.info("Normalizing contact information and address...")
    student_raw["contact_info"] = student_raw["contact_info"].apply(safe_parse)
    student_contact = pd.json_normalize(student_raw["contact_info"])
    student_contact.index = student_raw.index
    student_raw = student_raw.drop(columns=["contact_info"]).join(
        student_contact
    )

    split_address = student_raw["mailing_address"].str.split(
        r",\s*", expand=True, n=3
    )
    split_address.columns = ["street", "city", "state", "zip_code"]
    student_raw = student_raw.drop(columns=["mailing_address"]).join(
        split_address
    )

    # 5. Transform: Type Conversions & Missing Data Segregation
    logging.info("Coercing numeric data types and isolating missing records...")
    numeric_columns = [
        "num_course_taken",
        "job_id",
        "current_career_path_id",
        "time_spent_hrs",
    ]
    for col in numeric_columns:
        student_raw[col] = pd.to_numeric(student_raw[col], errors="coerce")

    # Isolate incomplete records for audit trail
    missing_courses = student_raw[student_raw["num_course_taken"].isnull()]
    student_raw = student_raw.dropna(subset=["num_course_taken"])

    missing_jobs = student_raw[student_raw["job_id"].isnull()]
    student_raw = student_raw.dropna(subset=["job_id"])

    missing_data = pd.concat([missing_courses, missing_jobs])
    logging.info(
        f"Segregated {len(missing_data)} incomplete rows to audit table."
    )

    # Impute missing career paths and hours
    student_raw["current_career_path_id"] = student_raw[
        "current_career_path_id"
    ].fillna(0)
    student_raw["time_spent_hrs"] = student_raw["time_spent_hrs"].fillna(0.0)

    # 6. Transform: Reference Table Updates
    not_applicable_career = {
        "career_path_id": 0,
        "career_path_name": "not applicable",
        "hours_to_complete": 0,
    }
    courses_raw.loc[len(courses_raw)] = not_applicable_career
    jobs_raw = jobs_raw.drop_duplicates()

    # 7. Merge Tables
    logging.info("Joining student records with reference tables...")
    student_raw["job_id"] = student_raw["job_id"].astype(int)
    student_raw["current_career_path_id"] = student_raw[
        "current_career_path_id"
    ].astype(int)

    final_df = student_raw.merge(
        courses_raw,
        left_on="current_career_path_id",
        right_on="career_path_id",
        how="left",
    ).drop(columns=["career_path_id"])

    final_df = final_df.merge(jobs_raw, on="job_id", how="left")

    # Final integer casting
    int_columns = [
        "job_id",
        "num_course_taken",
        "current_career_path_id",
        "age",
        "age_group",
    ]
    for col in int_columns:
        final_df[col] = final_df[col].astype(int)

    # 8. Load: Export Clean Data and Incomplete Records
    logging.info(f"Loading cleaned dataset to SQLite ({output_db})...")
    with sqlite3.connect(output_db) as out_conn:
        final_df.to_sql(
            "cademycode_aggregated", out_conn, if_exists="replace", index=False
        )
        missing_data.to_sql(
            "incomplete_data", out_conn, if_exists="replace", index=False
        )

    if output_csv:
        final_df.to_csv(output_csv, index=False)
        logging.info(f"Exported CSV copy to {output_csv}")

    duration = time.time() - start_time
    logging.info(
        f"Pipeline completed successfully in {duration:.2f}s! Cleaned records: {len(final_df)}"
    )


if __name__ == "__main__":
    try:
        run_pipeline(
            input_db="cademycode.db",
            output_db="cademy_cleansed.db",
            output_csv="cademycode_cleansed.csv",
        )
    except Exception as e:
        logging.exception(f"Pipeline execution failed: {e}")