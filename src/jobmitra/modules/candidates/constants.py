"""Candidate-stated classifications, independent of company industry and JD progress."""

from typing import Literal

Source = Literal["Walk-in", "Foundit", "WhatsApp", "Referral", "Existing database", "Other"]
SalaryPeriod = Literal["Monthly", "Annual", "Unknown"]
SalaryBasis = Literal["CTC", "Gross", "Take-home", "Unknown"]
RequestStatus = Literal["Searching", "Interviewing", "On Hold", "Placed", "Closed"]
AuthorityStatus = Literal["Not recorded", "Pending", "Signed (reported)", "Not signed"]
DocumentKind = Literal["ORIGINAL_RESUME", "MODIFIED_RESUME", "AUTHORITY"]
STATES = (
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chhattisgarh",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
)
UNION_TERRITORIES = (
    "Andaman and Nicobar Islands",
    "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi (NCT)",
    "Jammu and Kashmir",
    "Ladakh",
    "Lakshadweep",
    "Puducherry",
)
