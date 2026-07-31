import os

base_dir = r"c:\Users\harsh\OneDrive\Desktop\10_6\padosi_agent"

# 1. Truncate responsive.css to line 5768 (delete 5769-6280)
resp_file = os.path.join(base_dir, "static", "css", "responsive.css")
with open(resp_file, "r", encoding="utf-8") as f:
    resp_lines = f.readlines()
with open(resp_file, "w", encoding="utf-8") as f:
    f.writelines(resp_lines[:5768])
print(f"responsive.css new line count: {len(resp_lines[:5768])}")

# 2. Truncate custome.css to line 5246 (delete 5247-5254)
cust_file = os.path.join(base_dir, "static", "css", "custome.css")
with open(cust_file, "r", encoding="utf-8") as f:
    cust_lines = f.readlines()
with open(cust_file, "w", encoding="utf-8") as f:
    f.writelines(cust_lines[:5246])
print(f"custome.css new line count: {len(cust_lines[:5246])}")

# 3. Delete inline style block from footer.html (lines 108-158)
footer_file = os.path.join(base_dir, "templates", "partials", "footer.html")
with open(footer_file, "r", encoding="utf-8") as f:
    footer_lines = f.readlines()

# In Python list slicing, index 107 corresponds to line 108, and index 158 corresponds to line 159 (not inclusive)
new_footer_lines = footer_lines[:107] + footer_lines[158:]
with open(footer_file, "w", encoding="utf-8") as f:
    f.writelines(new_footer_lines)
print(f"footer.html updated. Deleted lines 108-158.")
