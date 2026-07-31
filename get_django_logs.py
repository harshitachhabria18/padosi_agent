import os

log_file = r"c:\Users\harsh\OneDrive\Desktop\10_6\padosi_agent\logs\django.log"
if os.path.exists(log_file):
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
        for line in lines[-5000:]: # check last 5000 lines
            if "Hallucinated insurance_type detected" in line:
                print(line.strip())
