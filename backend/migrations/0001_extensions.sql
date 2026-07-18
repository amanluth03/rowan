-- 0001_extensions: pgcrypto for gen_random_uuid, plus a UUID v7 helper.
--
-- ADR 0001: "UUID v7 (time-sortable) primary keys, generated app-side".
-- We generate v7 IDs in the application layer (app/ids.py) as the primary
-- path. This SQL-side generator exists as a fallback/default for rows
-- inserted outside the app (seed data, manual SQL, psql sessions) so the
-- schema is never dependent on app-side ID generation to be valid.
--
-- # ASSUMPTION: a pure-SQL UUIDv7 generator (timestamp-prefixed, random tail)
-- is sufficient for the fallback default; it does not need to be bit-for-bit
-- RFC 9562 compliant, only time-sortable, since the app always generates the
-- authoritative ID for rows created through the API.

create extension if not exists pgcrypto;

create or replace function uuid_generate_v7()
returns uuid
language sql
volatile
as $$
    select encode(
        set_bit(
            set_bit(
                overlay(
                    uuid_send(gen_random_uuid())
                    placing substring(int8send(floor(extract(epoch from clock_timestamp()) * 1000)::bigint) from 3)
                    from 1 for 6
                ),
                52, 1
            ),
            53, 0
        ),
        'hex'
    )::uuid;
$$;
