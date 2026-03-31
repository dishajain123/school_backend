"""
Seed default Standards (Class 1–12) and common subjects for a given school.

Usage:
    python -m scripts.seed_masters --school-id <UUID> --academic-year-id <UUID>
"""
import asyncio
import argparse
import uuid
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.masters import Standard, Subject, GradeMaster


DEFAULT_STANDARDS: list[dict] = [
    {"level": i, "name": f"Class {i}"} for i in range(1, 13)
]

# subjects mapped to level ranges
SUBJECT_MAP: list[dict] = [
    {"name": "English",     "code": "ENG",  "min_level": 1,  "max_level": 12},
    {"name": "Mathematics", "code": "MATH", "min_level": 1,  "max_level": 12},
    {"name": "Science",     "code": "SCI",  "min_level": 1,  "max_level": 10},
    {"name": "Social Studies", "code": "SST", "min_level": 1, "max_level": 10},
    {"name": "Hindi",       "code": "HIN",  "min_level": 1,  "max_level": 10},
    {"name": "Physics",     "code": "PHY",  "min_level": 11, "max_level": 12},
    {"name": "Chemistry",   "code": "CHEM", "min_level": 11, "max_level": 12},
    {"name": "Biology",     "code": "BIO",  "min_level": 11, "max_level": 12},
    {"name": "Accountancy", "code": "ACC",  "min_level": 11, "max_level": 12},
    {"name": "Economics",   "code": "ECO",  "min_level": 11, "max_level": 12},
    {"name": "Computer Science", "code": "CS", "min_level": 9, "max_level": 12},
    {"name": "Physical Education", "code": "PE", "min_level": 1, "max_level": 12},
]

DEFAULT_GRADES: list[dict] = [
    {"grade_letter": "A+", "min_percent": 90.0, "max_percent": 100.0, "grade_point": 10.0},
    {"grade_letter": "A",  "min_percent": 80.0, "max_percent": 89.99, "grade_point": 9.0},
    {"grade_letter": "B+", "min_percent": 70.0, "max_percent": 79.99, "grade_point": 8.0},
    {"grade_letter": "B",  "min_percent": 60.0, "max_percent": 69.99, "grade_point": 7.0},
    {"grade_letter": "C+", "min_percent": 50.0, "max_percent": 59.99, "grade_point": 6.0},
    {"grade_letter": "C",  "min_percent": 40.0, "max_percent": 49.99, "grade_point": 5.0},
    {"grade_letter": "D",  "min_percent": 33.0, "max_percent": 39.99, "grade_point": 4.0},
    {"grade_letter": "F",  "min_percent": 0.0,  "max_percent": 32.99, "grade_point": 0.0},
]


async def seed(school_id: uuid.UUID, academic_year_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        async with db.begin():
            # ── Standards ────────────────────────────────────────────────────
            standard_id_map: dict[int, uuid.UUID] = {}
            for s in DEFAULT_STANDARDS:
                existing = await db.execute(
                    select(Standard).where(
                        Standard.school_id == school_id,
                        Standard.level == s["level"],
                        Standard.academic_year_id == academic_year_id,
                    )
                )
                row = existing.scalar_one_or_none()
                if row is None:
                    obj = Standard(
                        school_id=school_id,
                        academic_year_id=academic_year_id,
                        name=s["name"],
                        level=s["level"],
                    )
                    db.add(obj)
                    await db.flush()
                    await db.refresh(obj)
                    standard_id_map[s["level"]] = obj.id
                    print(f"  [+] Standard: {s['name']}")
                else:
                    standard_id_map[s["level"]] = row.id
                    print(f"  [=] Standard already exists: {s['name']}")

            # ── Subjects ─────────────────────────────────────────────────────
            for sub in SUBJECT_MAP:
                for level in range(sub["min_level"], sub["max_level"] + 1):
                    std_id = standard_id_map.get(level)
                    if not std_id:
                        continue

                    code = f"{sub['code']}{level:02d}"
                    existing = await db.execute(
                        select(Subject).where(
                            Subject.school_id == school_id,
                            Subject.code == code,
                        )
                    )
                    row = existing.scalar_one_or_none()
                    if row is None:
                        obj = Subject(
                            school_id=school_id,
                            standard_id=std_id,
                            name=sub["name"],
                            code=code,
                        )
                        db.add(obj)
                        print(f"  [+] Subject: {sub['name']} (Class {level}) [{code}]")
                    else:
                        print(f"  [=] Subject exists: {code}")

            # ── Grade Master ─────────────────────────────────────────────────
            for g in DEFAULT_GRADES:
                existing = await db.execute(
                    select(GradeMaster).where(
                        GradeMaster.school_id == school_id,
                        GradeMaster.grade_letter == g["grade_letter"],
                    )
                )
                row = existing.scalar_one_or_none()
                if row is None:
                    obj = GradeMaster(
                        school_id=school_id,
                        grade_letter=g["grade_letter"],
                        min_percent=g["min_percent"],
                        max_percent=g["max_percent"],
                        grade_point=g["grade_point"],
                    )
                    db.add(obj)
                    print(f"  [+] Grade: {g['grade_letter']} ({g['min_percent']}–{g['max_percent']}%)")
                else:
                    print(f"  [=] Grade exists: {g['grade_letter']}")

        print("\n✅ Seed complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed default masters for a school")
    parser.add_argument("--school-id", required=True, type=uuid.UUID)
    parser.add_argument("--academic-year-id", required=True, type=uuid.UUID)
    args = parser.parse_args()

    print(f"\nSeeding masters for school={args.school_id}, year={args.academic_year_id}\n")
    asyncio.run(seed(args.school_id, args.academic_year_id))


if __name__ == "__main__":
    main()