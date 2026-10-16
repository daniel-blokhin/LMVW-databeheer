-- Generated from lmvw_pipeline.contracts. No source data or credentials.
-- First installation into an empty lmvw schema; do not disable constraints.
IF SCHEMA_ID(N'lmvw') IS NULL EXEC(N'CREATE SCHEMA [lmvw]');
GO

CREATE TABLE [lmvw].[pipeline_run] (
    [run_id] NVARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [delivery_id] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [mode] NVARCHAR(20) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [status] NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [snapshot_utc] DATETIMEOFFSET(7) NOT NULL,
    [started_at] DATETIMEOFFSET(7) NOT NULL,
    [completed_at] DATETIMEOFFSET(7) NOT NULL,
    [rule_version] NVARCHAR(32) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [config_sha256] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [source_metadata_json] NVARCHAR(MAX) NOT NULL,
    CONSTRAINT [PK_pipeline_run] PRIMARY KEY ([run_id])
);
GO

CREATE TABLE [lmvw].[source_status] (
    [run_id] NVARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [source_name] NVARCHAR(20) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [status] NVARCHAR(32) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [environment] NVARCHAR(32) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [record_count] BIGINT NOT NULL,
    [message] NVARCHAR(MAX) COLLATE Latin1_General_100_BIN2 NULL,
    CONSTRAINT [PK_source_status] PRIMARY KEY ([run_id], [source_name]),
    CONSTRAINT [FK_source_status_0] FOREIGN KEY ([run_id]) REFERENCES [lmvw].[pipeline_run] ([run_id])
);
GO

CREATE TABLE [lmvw].[plans] (
    [run_id] NVARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [record_id] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [delivery_id] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [source_row_number] BIGINT NOT NULL,
    [source_record_hash] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [municipality] NVARCHAR(300) COLLATE Latin1_General_100_BIN2 NULL,
    [plan_name] NVARCHAR(1000) COLLATE Latin1_General_100_BIN2 NULL,
    [koppelcode] NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NULL,
    [confidential] BIT NULL,
    [gross_capacity] BIGINT NULL,
    [demolition] BIGINT NULL,
    [net_capacity_reported] BIGINT NULL,
    [net_capacity_calculated] BIGINT NULL,
    [temporary_homes] BIGINT NULL,
    [plan_type] NVARCHAR(300) COLLATE Latin1_General_100_BIN2 NULL,
    [plan_status] NVARCHAR(300) COLLATE Latin1_General_100_BIN2 NULL,
    [status_code] NVARCHAR(8) COLLATE Latin1_General_100_BIN2 NULL,
    [hard_soft] NVARCHAR(16) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [geometry_wkt] NVARCHAR(MAX) COLLATE Latin1_General_100_BIN2 NULL,
    [geometry_geojson_wgs84] NVARCHAR(MAX) NULL,
    [crs] NVARCHAR(32) COLLATE Latin1_General_100_BIN2 NULL,
    [processing_status] NVARCHAR(16) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [error_count] BIGINT NOT NULL,
    [warning_count] BIGINT NOT NULL,
    [raw_payload_json] NVARCHAR(MAX) NOT NULL,
    CONSTRAINT [PK_plans] PRIMARY KEY ([run_id], [record_id]),
    CONSTRAINT [FK_plans_0] FOREIGN KEY ([run_id]) REFERENCES [lmvw].[pipeline_run] ([run_id])
);
GO

CREATE TABLE [lmvw].[plan_phasing] (
    [run_id] NVARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [record_id] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [period_start] BIGINT NOT NULL,
    [period_end] BIGINT NOT NULL,
    [period_label] NVARCHAR(80) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [sort_order] BIGINT NOT NULL,
    [planned_homes] BIGINT NULL,
    CONSTRAINT [PK_plan_phasing] PRIMARY KEY ([run_id], [record_id], [period_start], [period_end]),
    CONSTRAINT [FK_plan_phasing_0] FOREIGN KEY ([run_id]) REFERENCES [lmvw].[pipeline_run] ([run_id]),
    CONSTRAINT [FK_plan_phasing_1] FOREIGN KEY ([run_id], [record_id]) REFERENCES [lmvw].[plans] ([run_id], [record_id])
);
GO

CREATE TABLE [lmvw].[plan_breakdown] (
    [run_id] NVARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [record_id] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [category_group] NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [category_code] NVARCHAR(80) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [source_field] NVARCHAR(300) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [homes] BIGINT NULL,
    CONSTRAINT [PK_plan_breakdown] PRIMARY KEY ([run_id], [record_id], [category_group], [category_code]),
    CONSTRAINT [FK_plan_breakdown_0] FOREIGN KEY ([run_id]) REFERENCES [lmvw].[pipeline_run] ([run_id]),
    CONSTRAINT [FK_plan_breakdown_1] FOREIGN KEY ([run_id], [record_id]) REFERENCES [lmvw].[plans] ([run_id], [record_id])
);
GO

CREATE TABLE [lmvw].[quarantine] (
    [run_id] NVARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [record_id] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [source_row_number] BIGINT NOT NULL,
    [error_count] BIGINT NOT NULL,
    [raw_payload_json] NVARCHAR(MAX) NOT NULL,
    CONSTRAINT [PK_quarantine] PRIMARY KEY ([run_id], [record_id]),
    CONSTRAINT [FK_quarantine_0] FOREIGN KEY ([run_id]) REFERENCES [lmvw].[pipeline_run] ([run_id]),
    CONSTRAINT [FK_quarantine_1] FOREIGN KEY ([run_id], [record_id]) REFERENCES [lmvw].[plans] ([run_id], [record_id])
);
GO

CREATE TABLE [lmvw].[dq_issues] (
    [run_id] NVARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [issue_id] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [record_id] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NULL,
    [source_name] NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [source_object_id] NVARCHAR(2000) COLLATE Latin1_General_100_BIN2 NULL,
    [source_row_number] BIGINT NULL,
    [rule_id] NVARCHAR(80) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [category] NVARCHAR(40) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [severity] NVARCHAR(16) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [field_name] NVARCHAR(300) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [source_value] NVARCHAR(MAX) COLLATE Latin1_General_100_BIN2 NULL,
    [message] NVARCHAR(MAX) COLLATE Latin1_General_100_BIN2 NOT NULL,
    CONSTRAINT [PK_dq_issues] PRIMARY KEY ([run_id], [issue_id]),
    CONSTRAINT [FK_dq_issues_0] FOREIGN KEY ([run_id]) REFERENCES [lmvw].[pipeline_run] ([run_id]),
    CONSTRAINT [FK_dq_issues_1] FOREIGN KEY ([run_id], [record_id]) REFERENCES [lmvw].[plans] ([run_id], [record_id])
);
GO

CREATE TABLE [lmvw].[bag_panden] (
    [run_id] NVARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [bag_pand_id] NVARCHAR(16) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [source_feature_id] NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [retrieved_at] DATETIMEOFFSET(7) NOT NULL,
    [status] NVARCHAR(300) COLLATE Latin1_General_100_BIN2 NULL,
    [bouwjaar] BIGINT NULL,
    [aantal_verblijfsobjecten] BIGINT NULL,
    [gebruiksdoel] NVARCHAR(1000) COLLATE Latin1_General_100_BIN2 NULL,
    [documentdatum] DATE NULL,
    [documentnummer] NVARCHAR(1000) COLLATE Latin1_General_100_BIN2 NULL,
    [geometry_wkt] NVARCHAR(MAX) COLLATE Latin1_General_100_BIN2 NULL,
    [geometry_geojson_wgs84] NVARCHAR(MAX) NULL,
    [crs] NVARCHAR(32) COLLATE Latin1_General_100_BIN2 NULL,
    CONSTRAINT [PK_bag_panden] PRIMARY KEY ([run_id], [bag_pand_id]),
    CONSTRAINT [FK_bag_panden_0] FOREIGN KEY ([run_id]) REFERENCES [lmvw].[pipeline_run] ([run_id])
);
GO

CREATE TABLE [lmvw].[bag_verblijfsobjecten] (
    [run_id] NVARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [bag_verblijfsobject_id] NVARCHAR(16) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [source_feature_id] NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [retrieved_at] DATETIMEOFFSET(7) NOT NULL,
    [status] NVARCHAR(300) COLLATE Latin1_General_100_BIN2 NULL,
    [gebruiksdoel] NVARCHAR(1000) COLLATE Latin1_General_100_BIN2 NULL,
    [oppervlakte_m2] BIGINT NULL,
    [postcode] NVARCHAR(16) COLLATE Latin1_General_100_BIN2 NULL,
    [openbare_ruimte_naam] NVARCHAR(1000) COLLATE Latin1_General_100_BIN2 NULL,
    [huisnummer] BIGINT NULL,
    [huisletter] NVARCHAR(50) COLLATE Latin1_General_100_BIN2 NULL,
    [huisnummertoevoeging] NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NULL,
    [documentdatum] DATE NULL,
    [documentnummer] NVARCHAR(1000) COLLATE Latin1_General_100_BIN2 NULL,
    [geometry_wkt] NVARCHAR(MAX) COLLATE Latin1_General_100_BIN2 NULL,
    [geometry_geojson_wgs84] NVARCHAR(MAX) NULL,
    [crs] NVARCHAR(32) COLLATE Latin1_General_100_BIN2 NULL,
    CONSTRAINT [PK_bag_verblijfsobjecten] PRIMARY KEY ([run_id], [bag_verblijfsobject_id]),
    CONSTRAINT [FK_bag_verblijfsobjecten_0] FOREIGN KEY ([run_id]) REFERENCES [lmvw].[pipeline_run] ([run_id])
);
GO

CREATE TABLE [lmvw].[bag_vbo_pand] (
    [run_id] NVARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [bag_verblijfsobject_id] NVARCHAR(16) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [bag_pand_id] NVARCHAR(16) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [relation_basis] NVARCHAR(80) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [retrieved_at] DATETIMEOFFSET(7) NOT NULL,
    CONSTRAINT [PK_bag_vbo_pand] PRIMARY KEY ([run_id], [bag_verblijfsobject_id], [bag_pand_id]),
    CONSTRAINT [FK_bag_vbo_pand_0] FOREIGN KEY ([run_id]) REFERENCES [lmvw].[pipeline_run] ([run_id]),
    CONSTRAINT [FK_bag_vbo_pand_1] FOREIGN KEY ([run_id], [bag_verblijfsobject_id]) REFERENCES [lmvw].[bag_verblijfsobjecten] ([run_id], [bag_verblijfsobject_id]),
    CONSTRAINT [FK_bag_vbo_pand_2] FOREIGN KEY ([run_id], [bag_pand_id]) REFERENCES [lmvw].[bag_panden] ([run_id], [bag_pand_id])
);
GO

CREATE TABLE [lmvw].[brk_percelen] (
    [run_id] NVARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [brk_namespace] NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [brk_local_id] NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [source_feature_id] NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [retrieved_at] DATETIMEOFFSET(7) NOT NULL,
    [kadastrale_gemeente_code] NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NULL,
    [kadastrale_gemeente_naam] NVARCHAR(300) COLLATE Latin1_General_100_BIN2 NULL,
    [sectie] NVARCHAR(50) COLLATE Latin1_General_100_BIN2 NULL,
    [perceelnummer] BIGINT NULL,
    [kadastrale_grootte_m2] DECIMAL(38,12) NULL,
    [grootte_status] NVARCHAR(300) COLLATE Latin1_General_100_BIN2 NULL,
    [historie_status] NVARCHAR(300) COLLATE Latin1_General_100_BIN2 NULL,
    [geometry_wkt] NVARCHAR(MAX) COLLATE Latin1_General_100_BIN2 NULL,
    [geometry_geojson_wgs84] NVARCHAR(MAX) NULL,
    [crs] NVARCHAR(32) COLLATE Latin1_General_100_BIN2 NULL,
    CONSTRAINT [PK_brk_percelen] PRIMARY KEY ([run_id], [brk_namespace], [brk_local_id]),
    CONSTRAINT [FK_brk_percelen_0] FOREIGN KEY ([run_id]) REFERENCES [lmvw].[pipeline_run] ([run_id])
);
GO

CREATE TABLE [lmvw].[dso_documents] (
    [run_id] NVARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [document_id] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [source_type] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [environment] NVARCHAR(32) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [native_id] NVARCHAR(2000) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [document_type] NVARCHAR(500) COLLATE Latin1_General_100_BIN2 NULL,
    [title] NVARCHAR(4000) COLLATE Latin1_General_100_BIN2 NULL,
    [document_date] DATE NULL,
    [authority_name] NVARCHAR(1000) COLLATE Latin1_General_100_BIN2 NULL,
    [authority_code] NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NULL,
    [plan_status] NVARCHAR(300) COLLATE Latin1_General_100_BIN2 NULL,
    [rule_status] NVARCHAR(300) COLLATE Latin1_General_100_BIN2 NULL,
    [dossier_status] NVARCHAR(300) COLLATE Latin1_General_100_BIN2 NULL,
    [dossier_id] NVARCHAR(1000) COLLATE Latin1_General_100_BIN2 NULL,
    [reference_number] NVARCHAR(1000) COLLATE Latin1_General_100_BIN2 NULL,
    [publication_id] NVARCHAR(1000) COLLATE Latin1_General_100_BIN2 NULL,
    [geometry_ids_json] NVARCHAR(MAX) NOT NULL,
    [geometry_wkt] NVARCHAR(MAX) COLLATE Latin1_General_100_BIN2 NULL,
    [geometry_geojson_wgs84] NVARCHAR(MAX) NULL,
    [crs] NVARCHAR(32) COLLATE Latin1_General_100_BIN2 NULL,
    [geometry_status] NVARCHAR(32) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [text_status] NVARCHAR(32) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [source_url] NVARCHAR(4000) COLLATE Latin1_General_100_BIN2 NULL,
    [retrieved_at] DATETIMEOFFSET(7) NOT NULL,
    CONSTRAINT [PK_dso_documents] PRIMARY KEY ([run_id], [document_id]),
    CONSTRAINT [FK_dso_documents_0] FOREIGN KEY ([run_id]) REFERENCES [lmvw].[pipeline_run] ([run_id])
);
GO

CREATE TABLE [lmvw].[dso_document_text] (
    [run_id] NVARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [document_id] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [publication_text] NVARCHAR(MAX) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [text_sha256] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [character_count] BIGINT NOT NULL,
    [retrieved_at] DATETIMEOFFSET(7) NOT NULL,
    CONSTRAINT [PK_dso_document_text] PRIMARY KEY ([run_id], [document_id]),
    CONSTRAINT [FK_dso_document_text_0] FOREIGN KEY ([run_id]) REFERENCES [lmvw].[pipeline_run] ([run_id]),
    CONSTRAINT [FK_dso_document_text_1] FOREIGN KEY ([run_id], [document_id]) REFERENCES [lmvw].[dso_documents] ([run_id], [document_id])
);
GO

CREATE TABLE [lmvw].[plan_bag_vbo] (
    [run_id] NVARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [record_id] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [bag_verblijfsobject_id] NVARCHAR(16) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [match_method] NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [spatial_relation] NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
    CONSTRAINT [PK_plan_bag_vbo] PRIMARY KEY ([run_id], [record_id], [bag_verblijfsobject_id]),
    CONSTRAINT [FK_plan_bag_vbo_0] FOREIGN KEY ([run_id]) REFERENCES [lmvw].[pipeline_run] ([run_id]),
    CONSTRAINT [FK_plan_bag_vbo_1] FOREIGN KEY ([run_id], [record_id]) REFERENCES [lmvw].[plans] ([run_id], [record_id]),
    CONSTRAINT [FK_plan_bag_vbo_2] FOREIGN KEY ([run_id], [bag_verblijfsobject_id]) REFERENCES [lmvw].[bag_verblijfsobjecten] ([run_id], [bag_verblijfsobject_id])
);
GO

CREATE TABLE [lmvw].[plan_bag_pand] (
    [run_id] NVARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [record_id] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [bag_pand_id] NVARCHAR(16) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [match_method] NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [spatial_relation] NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [overlap_area_m2] DECIMAL(38,12) NULL,
    [via_vbo_count] BIGINT NOT NULL,
    CONSTRAINT [PK_plan_bag_pand] PRIMARY KEY ([run_id], [record_id], [bag_pand_id]),
    CONSTRAINT [FK_plan_bag_pand_0] FOREIGN KEY ([run_id]) REFERENCES [lmvw].[pipeline_run] ([run_id]),
    CONSTRAINT [FK_plan_bag_pand_1] FOREIGN KEY ([run_id], [record_id]) REFERENCES [lmvw].[plans] ([run_id], [record_id]),
    CONSTRAINT [FK_plan_bag_pand_2] FOREIGN KEY ([run_id], [bag_pand_id]) REFERENCES [lmvw].[bag_panden] ([run_id], [bag_pand_id])
);
GO

CREATE TABLE [lmvw].[plan_brk_perceel] (
    [run_id] NVARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [record_id] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [brk_namespace] NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [brk_local_id] NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [match_method] NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [intersection_area_m2] DECIMAL(38,12) NOT NULL,
    [overlap_pct_plan] DECIMAL(38,12) NOT NULL,
    [overlap_pct_perceel] DECIMAL(38,12) NOT NULL,
    CONSTRAINT [PK_plan_brk_perceel] PRIMARY KEY ([run_id], [record_id], [brk_namespace], [brk_local_id]),
    CONSTRAINT [FK_plan_brk_perceel_0] FOREIGN KEY ([run_id]) REFERENCES [lmvw].[pipeline_run] ([run_id]),
    CONSTRAINT [FK_plan_brk_perceel_1] FOREIGN KEY ([run_id], [record_id]) REFERENCES [lmvw].[plans] ([run_id], [record_id]),
    CONSTRAINT [FK_plan_brk_perceel_2] FOREIGN KEY ([run_id], [brk_namespace], [brk_local_id]) REFERENCES [lmvw].[brk_percelen] ([run_id], [brk_namespace], [brk_local_id])
);
GO

CREATE TABLE [lmvw].[plan_dso] (
    [run_id] NVARCHAR(36) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [record_id] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [document_id] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [search_geometry_hash] NVARCHAR(64) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [relation_basis] NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [relation_status] NVARCHAR(100) COLLATE Latin1_General_100_BIN2 NOT NULL,
    [spatial_verified] BIT NOT NULL,
    [substantively_confirmed] BIT NOT NULL,
    [overlap_area_m2] DECIMAL(38,12) NULL,
    [retrieved_at] DATETIMEOFFSET(7) NOT NULL,
    CONSTRAINT [PK_plan_dso] PRIMARY KEY ([run_id], [record_id], [document_id]),
    CONSTRAINT [FK_plan_dso_0] FOREIGN KEY ([run_id]) REFERENCES [lmvw].[pipeline_run] ([run_id]),
    CONSTRAINT [FK_plan_dso_1] FOREIGN KEY ([run_id], [record_id]) REFERENCES [lmvw].[plans] ([run_id], [record_id]),
    CONSTRAINT [FK_plan_dso_2] FOREIGN KEY ([run_id], [document_id]) REFERENCES [lmvw].[dso_documents] ([run_id], [document_id])
);
GO
