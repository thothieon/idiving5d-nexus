# app/routes_groups.py  ── Line@v260306
from fastapi import APIRouter, Depends
from app.auth_staff import get_current_staff, require_admin_staff
from app.db import get_conn

router = APIRouter()


@router.get("/groups")
async def list_groups(staff: dict = Depends(get_current_staff)):
    require_admin_staff(staff)
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT g.id, g.group_id, g.group_name, g.picture_url,
                       COUNT(gm.user_id) AS member_count,
                       g.updated_at
                FROM groups g
                LEFT JOIN group_members gm ON gm.group_id = g.id
                GROUP BY g.id
                ORDER BY g.updated_at DESC
                LIMIT 100
            """)
            return {"items": await cur.fetchall()}


@router.get("/groups/{group_id}/members")
async def get_group_members(group_id: str, staff: dict = Depends(get_current_staff)):
    require_admin_staff(staff)
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT gm.user_id, c.display_name, c.picture_url, gm.is_member, gm.joined_at
                FROM group_members gm
                LEFT JOIN customers c ON c.line_user_id = gm.user_id
                WHERE gm.group_id = %s
                ORDER BY gm.joined_at DESC
            """, (group_id,))
            return {"items": await cur.fetchall()}


@router.get("/customers/{customer_id}/identities")
async def get_customer_identities(customer_id: int, staff: dict = Depends(get_current_staff)):
    require_admin_staff(staff)
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT id, id_type, id_value, is_primary, verified, created_at
                FROM customer_identities
                WHERE customer_id = %s
                ORDER BY is_primary DESC, created_at DESC
            """, (customer_id,))
            return {"items": await cur.fetchall()}


@router.get("/customers/{customer_id}/sources")
async def get_customer_sources(customer_id: int, staff: dict = Depends(get_current_staff)):
    require_admin_staff(staff)
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT id, source_system, source_key, ingested_at, last_seen_at
                FROM customer_sources
                WHERE customer_id = %s
                ORDER BY last_seen_at DESC
            """, (customer_id,))
            return {"items": await cur.fetchall()}
