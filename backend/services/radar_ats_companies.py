"""
Compass — Permitted Public ATS Companies List for India Opportunities.

Data-only registry of public company job-board tokens for Greenhouse, Lever, and Ashby.
"""
from __future__ import annotations

from typing import List, Tuple

ATS_COMPANIES: List[Tuple[str, str, str]] = [
    # Greenhouse
    ("greenhouse", "groww", "Groww"),
    ("greenhouse", "phonepe", "PhonePe"),
    ("greenhouse", "razorpay", "Razorpay"),
    ("greenhouse", "postman", "Postman"),
    ("greenhouse", "cred", "CRED"),
    ("greenhouse", "meesho", "Meesho"),
    ("greenhouse", "swiggy", "Swiggy"),
    ("greenhouse", "freshworks", "Freshworks"),
    ("greenhouse", "atlassian", "Atlassian"),
    ("greenhouse", "uber", "Uber"),
    ("greenhouse", "databricks", "Databricks"),
    ("greenhouse", "stripe", "Stripe"),
    ("greenhouse", "cloudflare", "Cloudflare"),
    ("greenhouse", "gitlab", "GitLab"),
    ("greenhouse", "mongodb", "MongoDB"),
    ("greenhouse", "twilio", "Twilio"),
    ("greenhouse", "elastic", "Elastic"),
    ("greenhouse", "okta", "Okta"),
    ("greenhouse", "datadog", "Datadog"),
    ("greenhouse", "inmobi", "InMobi"),
    ("greenhouse", "canonical", "Canonical"),
    ("greenhouse", "rubrik", "Rubrik"),
    ("greenhouse", "airtel", "Airtel"),
    ("greenhouse", "urbancompany", "Urban Company"),
    ("greenhouse", "zeta", "Zeta"),
    # Lever
    ("lever", "paytm", "Paytm"),
    ("lever", "cred", "CRED"),
    ("lever", "hotstar", "Disney+ Hotstar"),
    ("lever", "clevertap", "CleverTap"),
    ("lever", "spotify", "Spotify"),
    # Ashby
    ("ashby", "ramp", "Ramp"),
    ("ashby", "notion", "Notion"),
    ("ashby", "synthesia", "Synthesia"),
    ("ashby", "linear", "Linear"),
    ("ashby", "openai", "OpenAI"),
    ("ashby", "sentry", "Sentry"),
    ("ashby", "retool", "Retool"),
]

COMPANIES = ATS_COMPANIES
