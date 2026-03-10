from core.supabase import supabase
import math

BUCKET = "stt-projects"

def format_size(bytes):
    for unit in ['B','KB','MB','GB']:
        if bytes < 1024:
            return f"{bytes:.2f} {unit}"
        bytes /= 1024
    return f"{bytes:.2f} TB"

def inspect_bucket():
    print(f"📦 Inspecting bucket: {BUCKET}")

    objects = supabase.storage.from_(BUCKET).list()

    if not objects:
        print("✔ Bucket empty.")
        return

    total_size = 0

    for obj in objects:
        print(f" - {obj['name']} ({format_size(obj['metadata']['size'])})")
        total_size += obj["metadata"]["size"]

    print("\n📌 Total files:", len(objects))
    print("📌 Total storage used:", format_size(total_size))
    free_limit = 1 * 1024 * 1024 * 1024  # 1GB
    print("📌 Estimated free remaining:", format_size(free_limit - total_size))

if __name__ == "__main__":
    inspect_bucket()
