-- Optional INTERNAL analytical views for the next phase. Run after schema.sql.
-- These views are not an authentication/authorisation boundary or a public export.
-- SQL Server execution has not been integration-tested in this release.
CREATE OR ALTER VIEW [lmvw].[v_accepted_plans_internal] AS
SELECT run_id, record_id, municipality, plan_name, koppelcode, confidential,
       gross_capacity, demolition, net_capacity_calculated,
       plan_type, plan_status, hard_soft, geometry_wkt, geometry_geojson_wgs84,
       processing_status
FROM [lmvw].[plans]
WHERE processing_status IN (N'READY', N'WARNING');
GO

-- Aggregate each relation independently before joining. Never multiply capacity
-- by joining BAG, BRK and DSO detail rows together.
CREATE OR ALTER VIEW [lmvw].[v_plan_source_counts_internal] AS
WITH vbo AS (
    SELECT run_id, record_id, COUNT_BIG(*) AS object_count
    FROM [lmvw].[plan_bag_vbo] GROUP BY run_id, record_id
), pand AS (
    SELECT run_id, record_id, COUNT_BIG(*) AS object_count
    FROM [lmvw].[plan_bag_pand] GROUP BY run_id, record_id
), parcel AS (
    SELECT run_id, record_id, COUNT_BIG(*) AS object_count
    FROM [lmvw].[plan_brk_perceel] GROUP BY run_id, record_id
), document AS (
    SELECT run_id, record_id, COUNT_BIG(*) AS candidate_count,
           SUM(CASE WHEN spatial_verified = 1 THEN CONVERT(BIGINT, 1) ELSE CONVERT(BIGINT, 0) END) AS verified_count
    FROM [lmvw].[plan_dso] GROUP BY run_id, record_id
)
SELECT p.run_id, p.record_id, p.municipality, p.plan_name, p.confidential,
       CASE WHEN sb.status IN (N'FIXTURES', N'LIVE', N'REPLAY', N'SNAPSHOTS') THEN COALESCE(v.object_count, 0) END AS bag_vbo_count,
       CASE WHEN sb.status IN (N'FIXTURES', N'LIVE', N'REPLAY', N'SNAPSHOTS') THEN COALESCE(b.object_count, 0) END AS bag_pand_count,
       CASE WHEN sk.status IN (N'FIXTURES', N'LIVE', N'REPLAY', N'SNAPSHOTS') THEN COALESCE(k.object_count, 0) END AS brk_parcel_count,
       CASE WHEN sd.status IN (N'FIXTURES', N'LIVE', N'REPLAY') OR sr.status IN (N'FIXTURES', N'LIVE', N'REPLAY')
            THEN COALESCE(d.candidate_count, 0) END AS dso_rp_candidate_count,
       CASE WHEN sd.status IN (N'FIXTURES', N'LIVE', N'REPLAY') OR sr.status IN (N'FIXTURES', N'LIVE', N'REPLAY')
            THEN COALESCE(d.verified_count, 0) END AS dso_rp_spatially_verified_count,
       sb.status AS bag_source_status, sk.status AS brk_source_status,
       sd.status AS dso_source_status, sr.status AS rp_source_status
FROM [lmvw].[v_accepted_plans_internal] p
LEFT JOIN vbo v ON v.run_id = p.run_id AND v.record_id = p.record_id
LEFT JOIN pand b ON b.run_id = p.run_id AND b.record_id = p.record_id
LEFT JOIN parcel k ON k.run_id = p.run_id AND k.record_id = p.record_id
LEFT JOIN document d ON d.run_id = p.run_id AND d.record_id = p.record_id
LEFT JOIN [lmvw].[source_status] sb ON sb.run_id = p.run_id AND sb.source_name = N'BAG'
LEFT JOIN [lmvw].[source_status] sk ON sk.run_id = p.run_id AND sk.source_name = N'BRK'
LEFT JOIN [lmvw].[source_status] sd ON sd.run_id = p.run_id AND sd.source_name = N'DSO'
LEFT JOIN [lmvw].[source_status] sr ON sr.run_id = p.run_id AND sr.source_name = N'RP';
GO

CREATE OR ALTER VIEW [lmvw].[v_capacity_by_municipality_internal] AS
SELECT run_id, municipality, confidential, hard_soft,
       COUNT_BIG(*) AS plan_record_count,
       SUM(gross_capacity) AS gross_capacity,
       SUM(demolition) AS planned_demolition,
       SUM(net_capacity_calculated) AS net_capacity
FROM [lmvw].[v_accepted_plans_internal]
GROUP BY run_id, municipality, confidential, hard_soft;
GO
