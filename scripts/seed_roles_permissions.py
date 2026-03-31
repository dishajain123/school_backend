"""
Seed script: roles and permissions.
Run once at setup — fully idempotent.

Usage:
    python -m scripts.seed_roles_permissions
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import AsyncSessionLocal
from app.repositories.rbac import RbacRepository
from app.utils.enums import RoleEnum


ALL_PERMISSIONS: list[tuple[str, str]] = [
    ("attendance:create",         "Mark attendance for a class"),
    ("attendance:read",           "View attendance records"),
    ("attendance:analytics",      "View attendance analytics and reports"),
    ("assignment:create",         "Create assignments"),
    ("assignment:read",           "View assignments"),
    ("submission:create",         "Submit assignment responses"),
    ("submission:grade",          "Grade student submissions"),
    ("homework:create",           "Create homework entries"),
    ("homework:read",             "View homework entries"),
    ("diary:create",              "Create student diary entries"),
    ("diary:read",                "View student diary entries"),
    ("exam_schedule:create",      "Create exam schedules"),
    ("exam_schedule:read",        "View exam schedules"),
    ("fee:create",                "Create and manage fee structures and payments"),
    ("fee:read",                  "View fee records"),
    ("result:create",             "Enter student exam results"),
    ("result:publish",            "Publish results to students and parents"),
    ("announcement:create",       "Create school announcements"),
    ("gallery:create",            "Upload photos and manage gallery albums"),
    ("gallery:read",              "View gallery albums and photos"),
    ("leave:apply",               "Apply for teacher leave"),
    ("leave:approve",             "Approve or reject teacher leave"),
    ("leave:read",                "View leave records"),
    ("chat:message",              "Send and receive chat messages"),
    ("chat:group_manage",         "Create and manage group conversations"),
    ("document:generate",         "Request document generation"),
    ("document:manage",           "Manage all school documents"),
    ("teacher_assignment:manage", "Assign teachers to classes and subjects"),
    ("academic_year:manage",      "Manage academic years and rollover"),
    ("student:promote",           "Promote or hold back students"),
    ("settings:manage",           "Manage school settings"),
    ("user:manage",               "Create and manage user accounts"),
    ("report:read",               "View school-wide reports"),
    ("complaint:create",          "Submit complaints"),
    ("complaint:read",            "View and manage complaints"),
    ("behaviour_log:create",      "Log student behaviour incidents"),
    ("behaviour_log:read",        "View student behaviour logs"),
    ("school:manage",             "Create and manage schools (superadmin only)"),
]

ROLE_DEFINITIONS: dict[str, str] = {
    RoleEnum.SUPERADMIN.value: "Full system access including multi-school management",
    RoleEnum.PRINCIPAL.value:  "Full operational control of a school",
    RoleEnum.TRUSTEE.value:    "Read-only oversight and financial reporting",
    RoleEnum.TEACHER.value:    "Academic operations scoped to assigned classes",
    RoleEnum.STUDENT.value:    "Access to own academic data and submissions",
    RoleEnum.PARENT.value:     "Access to linked children's data",
}

ROLE_PERMISSIONS: dict[str, list[str]] = {
    RoleEnum.SUPERADMIN.value: [code for code, _ in ALL_PERMISSIONS],

    RoleEnum.PRINCIPAL.value: [
        code for code, _ in ALL_PERMISSIONS
        if code not in ("school:manage", "leave:apply")
    ],

    RoleEnum.TRUSTEE.value: [
        "attendance:read",
        "attendance:analytics",
        "assignment:read",
        "homework:read",
        "diary:read",
        "exam_schedule:read",
        "fee:read",
        "gallery:read",
        "leave:read",
        "report:read",
        "complaint:read",
        "behaviour_log:read",
        "announcement:create",
    ],

    RoleEnum.TEACHER.value: [
        "attendance:create",
        "attendance:read",
        "attendance:analytics",
        "assignment:create",
        "assignment:read",
        "submission:grade",
        "homework:create",
        "homework:read",
        "diary:create",
        "diary:read",
        "exam_schedule:read",
        "result:create",
        "announcement:create",
        "gallery:create",
        "gallery:read",
        "leave:apply",
        "chat:message",
        "behaviour_log:create",
        "behaviour_log:read",
    ],

    # STUDENT: no result:create — students do not enter exam marks
    RoleEnum.STUDENT.value: [
        "attendance:read",
        "assignment:read",
        "submission:create",
        "homework:read",
        "diary:read",
        "exam_schedule:read",
        "fee:read",
        "gallery:read",
        "chat:message",
        "document:generate",
        "complaint:create",
    ],

    RoleEnum.PARENT.value: [
        "attendance:read",
        "attendance:analytics",
        "assignment:read",
        "submission:create",
        "homework:read",
        "diary:read",
        "exam_schedule:read",
        "fee:read",
        "gallery:read",
        "chat:message",
        "document:generate",
        "complaint:create",
        "complaint:read",
        "behaviour_log:read",
    ],
}


async def seed(db: AsyncSession) -> None:
    repo = RbacRepository(db)

    print("→ Seeding permissions...")
    perm_map: dict[str, object] = {}
    for code, description in ALL_PERMISSIONS:
        perm = await repo.upsert_permission(code, description)
        perm_map[code] = perm
    print(f"  ✓ {len(perm_map)} permissions ready")

    print("→ Seeding roles...")
    role_map: dict[str, object] = {}
    for role_name, description in ROLE_DEFINITIONS.items():
        role = await repo.upsert_role(role_name, description)
        role_map[role_name] = role
    print(f"  ✓ {len(role_map)} roles ready")

    print("→ Assigning permissions to roles...")
    total_assignments = 0
    for role_name, permission_codes in ROLE_PERMISSIONS.items():
        role = role_map[role_name]
        for code in permission_codes:
            perm = perm_map.get(code)
            if perm:
                await repo.assign_permission_to_role(role.id, perm.id)
                total_assignments += 1
    print(f"  ✓ {total_assignments} role-permission assignments ready")

    await db.commit()
    print("\n✅ Seed completed successfully")


async def main() -> None:
    print("SMS Backend — Seeding Roles & Permissions\n")
    async with AsyncSessionLocal() as db:
        try:
            await seed(db)
        except Exception as e:
            await db.rollback()
            print(f"\n❌ Seed failed: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(main())