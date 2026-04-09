import json
import os
from glob import glob
import math

def load_json_file(file_path):
    with open(file_path, "r") as f:
        return json.load(f)


def load_multiple_files(folder_path):
    records = []
    for file_path in glob(os.path.join(folder_path, "*.json")):
        try:
            data = load_json_file(file_path)
            if isinstance(data, list):
                records.extend(data)
        except Exception as e:
            print(f"❌ Error loading {file_path}: {e}")
    return records


def generate_key(record):
    email = (record.get("email") or "").lower().strip()
    linkedin = (record.get("linkedin") or "").lower().strip()

    if email:
        return f"email:{email}"
    elif linkedin:
        return f"linkedin:{linkedin}"
    else:
        name = (record.get("full_name") or "").lower().strip()
        company = (record.get("company_name") or "").lower().strip()
        return f"name_company:{name}_{company}"


def get_existing_keys(existing_records):
    keys = set()
    for r in existing_records:
        keys.add(generate_key(r))
    return keys


def filter_new_leads(new_file, existing_folder, output_file="net_new_leads.json"):
    print("📂 Loading existing leads...")
    existing_records = load_multiple_files(existing_folder)
    existing_keys = get_existing_keys(existing_records)
    print(f"✅ Existing leads: {len(existing_keys)} unique keys")

    print("📥 Loading new leads...")
    new_records = load_json_file(new_file)
    print(f"➡️ Incoming leads: {len(new_records)}")

    net_new = []
    skipped = 0

    for record in new_records:
        key = generate_key(record)

        if key not in existing_keys:
            net_new.append(record)
            existing_keys.add(key)  # prevent dupes within new file
        else:
            skipped += 1

    print(f"🆕 New leads: {len(net_new)}")
    print(f"⏭️ Skipped (already existed): {skipped}")

    with open(output_file, "w") as f:
        json.dump(net_new, f, indent=2)

    print(f"💾 Saved to {output_file}")

    return net_new




def chunk_and_save(records, output_dir="chunks", chunk_size=100, prefix="net_new_leads"):
    os.makedirs(output_dir, exist_ok=True)

    total = len(records)
    num_chunks = math.ceil(total / chunk_size)

    print(f"📦 Splitting {total} records into {num_chunks} chunks of {chunk_size}")

    for i in range(num_chunks):
        start = i * chunk_size
        end = start + chunk_size
        chunk = records[start:end]

        filename = f"{prefix}_{i+1}.json"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, "w") as f:
            json.dump(chunk, f, indent=2)

        print(f"💾 Saved {len(chunk)} records → {filepath}")

# Example usage:
if __name__ == "__main__":
    pathname = "../data/raw_leads"
    net_new = filter_new_leads(
        new_file=os.path.join(pathname, "dataset_leads-finder_2026-04-08_16-26-29-990.json"),
        existing_folder=os.path.join(pathname, "completed"),
        output_file="net_new_leads.json"
    )

    chunk_and_save(
        net_new,
        output_dir=os.path.join(pathname, "chunks"),
        chunk_size=100
    )