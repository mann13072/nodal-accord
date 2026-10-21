# Canonical data dictionary

All facts are fabricated; money is EUR, quantities are integer EA, machine time is hours. ISO dates are Monday-start buckets; timestamps include UTC offsets. Decimals use ROUND_HALF_UP. Every table includes stable identity, record/schema versions, source lineage, validity and classification. `tenant_id` = `buyer_tenant_id`; `classification` = `data_classification`. Global supplier identity is never partitioned by buyer. Tenant tables use `table.parquet/tenant_id=.../part-00000.parquet`; retain tenant columns when reading individual files. `common.load_table` handles both layouts.

Blueprint table aliases: `bill_of_materials` → `bom_edges`; `capacity_requirements` → `resource_lane_requirements`; `commercial_terms` → `buyer_commercial_terms`; `buyer_financial_assumptions` → `buyer_financial_profiles`; `organization_memberships` → `supplier_user_roles`. These aliases document handoff joins without duplicating tables.

## organizations

Primary key: `org_id`. Classification: `PUBLIC_SYNTHETIC`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `org_id` | `string` | org id; stable foreign/entity identifier |
| `org_type` | `string` | org type |
| `display_name` | `string` | display name |
| `supplier_segment` | `string` | supplier segment |
| `size_band` | `string` | size band |
| `region` | `string` | region |
| `country` | `string` | country |
| `status` | `string` | status |
| `synthetic_latitude` | `double` | synthetic latitude |
| `synthetic_longitude` | `double` | synthetic longitude |
| `id` | `string` | id |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## tenants

Primary key: `tenant_id`. Classification: `PUBLIC_SYNTHETIC`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `buyer_org_id` | `string` | buyer org id; stable foreign/entity identifier |
| `isolation_policy` | `string` | isolation policy |
| `default_currency` | `string` | default currency |
| `status` | `string` | status |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## plants

Primary key: `plant_id`. Classification: `BUYER_INTERNAL`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `plant_id` | `string` | plant id; stable foreign/entity identifier |
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `region` | `string` | region |
| `country` | `string` | country |
| `timezone` | `string` | timezone |
| `planning_calendar_id` | `string` | planning calendar id; stable foreign/entity identifier |
| `plant_type` | `string` | plant type |
| `currency` | `string` | currency |
| `synthetic_latitude` | `int64` | synthetic latitude |
| `synthetic_longitude` | `int64` | synthetic longitude |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## trading_relationships

Primary key: `relationship_id`. Classification: `RELATIONSHIP_SHARED`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `relationship_id` | `string` | relationship id; stable foreign/entity identifier |
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `buyer_org_id` | `string` | buyer org id; stable foreign/entity identifier |
| `supplier_org_id` | `string` | supplier org id; stable foreign/entity identifier |
| `status` | `string` | status |
| `effective_from` | `string` | effective from |
| `effective_to` | `string` | effective to |
| `sharing_policy_id` | `string` | sharing policy id; stable foreign/entity identifier |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## sharing_policies

Primary key: `sharing_policy_id`. Classification: `PLATFORM_AUDIT_RESTRICTED`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `sharing_policy_id` | `string` | sharing policy id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `recipient_org_id` | `string` | recipient org id; stable foreign/entity identifier |
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `allowed_entity` | `string` | allowed entity |
| `allowed_fields` | `list<item: string>` | allowed fields |
| `purpose` | `string` | purpose |
| `effective_to` | `string` | effective to |
| `policy_version` | `int64` | policy version |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## parts

Primary key: `part_id`. Classification: `BUYER_INTERNAL`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `part_id` | `string` | part id; stable foreign/entity identifier |
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `part_family_id` | `string` | part family id; stable foreign/entity identifier |
| `description` | `string` | description |
| `supplier_segment` | `string` | supplier segment |
| `base_unit` | `string` | base unit |
| `criticality` | `string` | criticality |
| `average_unit_value_eur` | `decimal128(20, 2)` | average unit value eur; Decimal EUR, not a float |
| `life_cycle` | `string` | life cycle |
| `valid_from` | `string` | valid from |
| `base_weekly_units` | `int64` | base weekly units; nonnegative integer EA |
| `assigned_plant_id` | `string` | assigned plant id; stable foreign/entity identifier |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_to` | `string` | Exclusive validity endpoint |
| `currency` | `string` | currency |

## plant_part_assignments

Primary key: `tenant_id, plant_id, part_id`. Classification: `BUYER_INTERNAL`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `plant_id` | `string` | plant id; stable foreign/entity identifier |
| `part_id` | `string` | part id; stable foreign/entity identifier |
| `consumption_role` | `string` | consumption role |
| `active_from` | `string` | active from |
| `active_to` | `string` | active to |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## sourcing_lanes

Primary key: `lane_id`. Classification: `RELATIONSHIP_SHARED`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `lane_id` | `string` | lane id; stable foreign/entity identifier |
| `relationship_id` | `string` | relationship id; stable foreign/entity identifier |
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `buyer_org_id` | `string` | buyer org id; stable foreign/entity identifier |
| `supplier_org_id` | `string` | supplier org id; stable foreign/entity identifier |
| `part_id` | `string` | part id; stable foreign/entity identifier |
| `destination_plant_id` | `string` | destination plant id; stable foreign/entity identifier |
| `qualified` | `bool` | qualified |
| `lead_time_days` | `int64` | lead time days |
| `transport_mode` | `string` | transport mode |
| `transport_band` | `string` | transport band |
| `min_order_qty` | `int64` | min order qty; nonnegative integer EA |
| `lot_multiple` | `int64` | lot multiple |
| `max_weekly_units` | `int64` | max weekly units; nonnegative integer EA |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |
| `standard_landed_unit_price_eur` | `decimal128(20, 2)` | standard landed unit price eur; Decimal EUR, not a float |
| `nominal_weekly_units` | `int64` | nominal weekly units; nonnegative integer EA |
| `source_count` | `int64` | source count |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `currency` | `string` | currency |

## bom_edges

Primary key: `tenant_id, plant_id, parent_part_id, child_part_id, bom_revision`. Classification: `BUYER_INTERNAL`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `plant_id` | `string` | plant id; stable foreign/entity identifier |
| `parent_part_id` | `string` | parent part id; stable foreign/entity identifier |
| `child_part_id` | `string` | child part id; stable foreign/entity identifier |
| `quantity_per_parent` | `int64` | quantity per parent |
| `scrap_factor` | `decimal128(20, 2)` | scrap factor |
| `bom_revision` | `int64` | bom revision |
| `effective_from` | `string` | effective from |
| `effective_to` | `string` | effective to |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## resource_lane_requirements

Primary key: `lane_id, resource_id`. Classification: `SUPPLIER_INTERNAL`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `lane_id` | `string` | lane id; stable foreign/entity identifier |
| `resource_id` | `string` | resource id; stable foreign/entity identifier |
| `supplier_org_id` | `string` | supplier org id; stable foreign/entity identifier |
| `hours_per_unit` | `decimal128(20, 6)` | hours per unit |
| `setup_hours_if_activated` | `decimal128(20, 6)` | setup hours if activated |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |
| `id` | `string` | id |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |

## capacity_resources

Primary key: `resource_id`. Classification: `SUPPLIER_INTERNAL`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `resource_id` | `string` | resource id; stable foreign/entity identifier |
| `supplier_org_id` | `string` | supplier org id; stable foreign/entity identifier |
| `resource_type` | `string` | resource type |
| `part_family_id` | `null` | part family id; stable foreign/entity identifier |
| `confidentiality` | `string` | confidentiality |
| `rated_hours_per_week` | `decimal128(20, 6)` | rated hours per week |
| `efficiency_factor` | `decimal128(20, 2)` | efficiency factor |
| `valid_from` | `string` | valid from |
| `id` | `string` | id |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_to` | `string` | Exclusive validity endpoint |

## capacity_calendar

Primary key: `resource_id, week_start`. Classification: `SUPPLIER_INTERNAL`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `resource_id` | `string` | resource id; stable foreign/entity identifier |
| `supplier_org_id` | `string` | supplier org id; stable foreign/entity identifier |
| `week_start` | `string` | week start; Monday YYYY-MM-DD |
| `available_hours` | `decimal128(20, 4)` | One resource/week physical budget; subtract firm reservations for newly allocatable work |
| `maintenance_hours` | `decimal128(20, 4)` | maintenance hours |
| `firm_reserved_hours` | `decimal128(20, 5)` | Locked external work; not freely reallocatable across buyers |
| `flexible_additional_hours` | `decimal128(20, 3)` | flexible additional hours |
| `flex_mechanism` | `string` | flex mechanism |
| `data_confidence` | `decimal128(20, 2)` | data confidence |
| `id` | `string` | id |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## planning_weeks

Primary key: `week_index`. Classification: `PUBLIC_SYNTHETIC`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `week_start` | `string` | week start; Monday YYYY-MM-DD |
| `week_end_exclusive` | `string` | week end exclusive; Monday YYYY-MM-DD |
| `week_index` | `int64` | week index |
| `iso_week` | `int64` | iso week |
| `planning_timezone_rule` | `string` | planning timezone rule |
| `id` | `string` | id |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## lane_capacity

Primary key: `lane_id, week_start`. Classification: `RELATIONSHIP_SHARED`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `lane_id` | `string` | lane id; stable foreign/entity identifier |
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `supplier_org_id` | `string` | supplier org id; stable foreign/entity identifier |
| `week_start` | `string` | week start; Monday YYYY-MM-DD |
| `committed_units` | `int64` | committed units; nonnegative integer EA |
| `supplier_offered_flex_units` | `int64` | supplier offered flex units; nonnegative integer EA |
| `confidence` | `double` | confidence |
| `confirmed_at` | `string` | confirmed at |
| `source_version` | `int64` | source version |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## demand_forecast

Primary key: `tenant_id, plant_id, part_id, week_start, revision`. Classification: `BUYER_INTERNAL`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `plant_id` | `string` | plant id; stable foreign/entity identifier |
| `part_id` | `string` | part id; stable foreign/entity identifier |
| `week_start` | `string` | week start; Monday YYYY-MM-DD |
| `required_units` | `int64` | required units; nonnegative integer EA |
| `revision` | `int64` | revision |
| `firm_or_forecast` | `string` | firm or forecast |
| `source_update_at` | `string` | source update at |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## inventory_positions

Primary key: `tenant_id, plant_id, part_id, snapshot_at`. Classification: `BUYER_INTERNAL`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `plant_id` | `string` | plant id; stable foreign/entity identifier |
| `part_id` | `string` | part id; stable foreign/entity identifier |
| `snapshot_at` | `string` | snapshot at |
| `on_hand_units` | `int64` | on hand units; nonnegative integer EA |
| `reserved_units` | `int64` | reserved units; nonnegative integer EA |
| `quality_hold_units` | `int64` | quality hold units; nonnegative integer EA |
| `usable_units` | `int64` | on_hand_units - reserved_units - quality_hold_units; nonnegative |
| `valuation_unit_cost_eur` | `decimal128(20, 2)` | valuation unit cost eur; Decimal EUR, not a float |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |
| `currency` | `string` | currency |

## supplier_private_economics

Primary key: `supplier_org_id, lane_id`. Classification: `SUPPLIER_INTERNAL`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `supplier_org_id` | `string` | supplier org id; stable foreign/entity identifier |
| `lane_id` | `string` | lane id; stable foreign/entity identifier |
| `unit_variable_cost_eur` | `decimal128(20, 2)` | Supplier-private physical variable production cost; never a buyer purchase price |
| `overtime_premium_cost_eur_per_unit` | `decimal128(20, 2)` | overtime premium cost eur per unit; Decimal EUR, not a float |
| `minimum_acceptable_margin_eur_per_unit` | `decimal128(20, 2)` | minimum acceptable margin eur per unit; Decimal EUR, not a float |
| `max_flex_units_per_week` | `int64` | max flex units per week; nonnegative integer EA |
| `internal_financing_rate_annual` | `decimal128(20, 6)` | internal financing rate annual |
| `weak_margin_flag` | `bool` | weak margin flag |
| `id` | `string` | id |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |
| `currency` | `string` | currency |

## buyer_commercial_terms

Primary key: `relationship_id, part_id, valid_from`. Classification: `BUYER_INTERNAL`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `relationship_id` | `string` | relationship id; stable foreign/entity identifier |
| `part_id` | `string` | part id; stable foreign/entity identifier |
| `valid_from` | `string` | valid from |
| `unit_price_eur` | `decimal128(20, 2)` | unit price eur; Decimal EUR, not a float |
| `base_transport_cost_eur_per_unit` | `decimal128(20, 2)` | base transport cost eur per unit; Decimal EUR, not a float |
| `payment_days` | `int64` | payment days |
| `max_approved_premium_pct` | `decimal128(20, 6)` | max approved premium pct |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_to` | `string` | Exclusive validity endpoint |
| `currency` | `string` | currency |

## buyer_financial_profiles

Primary key: `tenant_id`. Classification: `BUYER_INTERNAL`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `inventory_holding_rate_annual` | `decimal128(20, 6)` | inventory holding rate annual |
| `cash_financing_rate_annual` | `decimal128(20, 6)` | cash financing rate annual |
| `stockout_exposure_proxy_eur_per_unit` | `decimal128(20, 2)` | stockout exposure proxy eur per unit; Decimal EUR, not a float |
| `max_case_incremental_spend_eur` | `decimal128(20, 2)` | max case incremental spend eur; Decimal EUR, not a float |
| `approval_threshold_eur` | `decimal128(20, 2)` | approval threshold eur; Decimal EUR, not a float |
| `pricing_basis` | `string` | pricing basis |
| `scenario_version` | `int64` | scenario version |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |
| `currency` | `string` | currency |

## purchase_orders

Primary key: `po_id`. Classification: `BUYER_INTERNAL`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `po_id` | `string` | po id; stable foreign/entity identifier |
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `buyer_org_id` | `string` | buyer org id; stable foreign/entity identifier |
| `supplier_org_id` | `string` | supplier org id; stable foreign/entity identifier |
| `order_date` | `string` | order date |
| `status` | `string` | status |
| `currency` | `string` | currency |
| `relationship_id` | `string` | relationship id; stable foreign/entity identifier |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## purchase_order_lines

Primary key: `po_line_id`. Classification: `BUYER_INTERNAL`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `po_line_id` | `string` | po line id; stable foreign/entity identifier |
| `po_id` | `string` | po id; stable foreign/entity identifier |
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `lane_id` | `string` | lane id; stable foreign/entity identifier |
| `part_id` | `string` | part id; stable foreign/entity identifier |
| `destination_plant_id` | `string` | destination plant id; stable foreign/entity identifier |
| `ordered_qty` | `int64` | ordered qty; nonnegative integer EA |
| `confirmed_qty` | `int64` | confirmed qty; nonnegative integer EA |
| `unit_purchase_price` | `decimal128(20, 2)` | unit purchase price; Decimal EUR, not a float |
| `currency` | `string` | currency |
| `due_date` | `string` | due date |
| `line_status` | `string` | line status |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## scheduled_receipts

Primary key: `receipt_id`. Classification: `BUYER_INTERNAL`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `receipt_id` | `string` | receipt id; stable foreign/entity identifier |
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `po_line_id` | `string` | po line id; stable foreign/entity identifier |
| `lane_id` | `string` | lane id; stable foreign/entity identifier |
| `part_id` | `string` | part id; stable foreign/entity identifier |
| `destination_plant_id` | `string` | destination plant id; stable foreign/entity identifier |
| `receipt_qty` | `int64` | receipt qty; nonnegative integer EA |
| `expected_arrival_at` | `string` | expected arrival at |
| `status` | `string` | status |
| `source_version` | `int64` | source version |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## disruption_events

Primary key: `disruption_id`. Classification: `PLATFORM_AUDIT_RESTRICTED`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `disruption_id` | `string` | disruption id; stable foreign/entity identifier |
| `tenant_scope` | `string` | tenant scope |
| `supplier_org_id` | `string` | supplier org id; stable foreign/entity identifier |
| `resource_id` | `string` | resource id; stable foreign/entity identifier |
| `lane_id` | `string` | lane id; stable foreign/entity identifier |
| `event_type` | `string` | event type |
| `start_week` | `string` | start week; Monday YYYY-MM-DD |
| `duration_weeks` | `int64` | duration weeks |
| `capacity_loss_percent` | `decimal128(20, 6)` | capacity loss percent |
| `demand_increase_percent` | `decimal128(20, 6)` | demand increase percent |
| `lead_time_extension_days` | `int64` | lead time extension days |
| `event_confidence` | `decimal128(20, 6)` | event confidence |
| `is_confirmed` | `bool` | is confirmed |
| `synthetic_root_cause` | `string` | synthetic root cause |
| `event_version` | `int64` | event version |
| `expected_impacted_entities` | `string` | expected impacted entities |
| `severity_model_version` | `string` | severity model version |
| `application_mode` | `string` | application mode |
| `id` | `string` | id |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## scenario_oracle

Primary key: `scenario_id`. Classification: `PLATFORM_AUDIT_RESTRICTED`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `scenario_id` | `string` | scenario id; stable foreign/entity identifier |
| `baseline_snapshot_id` | `string` | baseline snapshot id; stable foreign/entity identifier |
| `disruption_event_ids` | `list<item: string>` | disruption event ids |
| `known_affected_supplier_ids` | `list<item: string>` | known affected supplier ids |
| `known_affected_part_ids` | `list<item: string>` | known affected part ids |
| `known_affected_plant_ids` | `list<item: string>` | known affected plant ids |
| `first_at_risk_week` | `string` | first at risk week; Monday YYYY-MM-DD |
| `at_risk_units_from_deterministic_baseline` | `int64` | at risk units from deterministic baseline; nonnegative integer EA |
| `feasible_mitigation_modes` | `list<item: string>` | feasible mitigation modes |
| `expected_constraint_flags` | `list<item: string>` | expected constraint flags |
| `oracle_generation_method` | `string` | oracle generation method |
| `snapshot_content_hash` | `string` | snapshot content hash |
| `id` | `string` | id |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## resolution_cases

Primary key: `case_id`. Classification: `BUYER_INTERNAL`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `case_id` | `string` | case id; stable foreign/entity identifier |
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `exception_id` | `string` | exception id; stable foreign/entity identifier |
| `snapshot_id` | `string` | snapshot id; stable foreign/entity identifier |
| `status` | `string` | status |
| `owner_principal_id` | `string` | owner principal id; stable foreign/entity identifier |
| `impact_score` | `int64` | impact score |
| `opened_at` | `string` | opened at |
| `last_updated_at` | `string` | last updated at |
| `shared_supplier_org_ids` | `list<item: string>` | shared supplier org ids |
| `category` | `string` | category |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## offers

Primary key: `offer_id`. Classification: `RELATIONSHIP_SHARED`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `offer_id` | `string` | offer id; stable foreign/entity identifier |
| `case_id` | `string` | case id; stable foreign/entity identifier |
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `sender_org_id` | `string` | sender org id; stable foreign/entity identifier |
| `recipient_org_id` | `string` | recipient org id; stable foreign/entity identifier |
| `offer_version` | `int64` | offer version |
| `status` | `string` | status |
| `created_at` | `string` | created at |
| `expires_at` | `string` | expires at |
| `quoted_terms_hash` | `string` | quoted terms hash |
| `is_shareable` | `bool` | is shareable |
| `line_items` | `list<item: string>` | line items |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## offer_lines

Primary key: `offer_line_id`. Classification: `RELATIONSHIP_SHARED`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `offer_line_id` | `string` | offer line id; stable foreign/entity identifier |
| `offer_id` | `string` | offer id; stable foreign/entity identifier |
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `lane_id` | `string` | lane id; stable foreign/entity identifier |
| `part_id` | `string` | part id; stable foreign/entity identifier |
| `delivery_week` | `string` | delivery week; Monday YYYY-MM-DD |
| `additional_qty` | `int64` | additional qty; nonnegative integer EA |
| `unit_premium_eur` | `decimal128(20, 2)` | unit premium eur; Decimal EUR, not a float |
| `payment_days` | `int64` | payment days |
| `conditions` | `string` | conditions |
| `source_scenario_id` | `string` | source scenario id; stable foreign/entity identifier |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |
| `currency` | `string` | currency |

## counteroffers

Primary key: `counteroffer_id`. Classification: `RELATIONSHIP_SHARED`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `counteroffer_id` | `string` | counteroffer id; stable foreign/entity identifier |
| `parent_offer_id` | `string` | parent offer id; stable foreign/entity identifier |
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `supplier_org_id` | `string` | supplier org id; stable foreign/entity identifier |
| `new_version` | `int64` | new version |
| `countered_capacity` | `int64` | countered capacity |
| `countered_delivery_week` | `string` | countered delivery week; Monday YYYY-MM-DD |
| `countered_premium` | `decimal128(20, 2)` | countered premium; Decimal EUR, not a float |
| `countered_payment_days` | `int64` | countered payment days |
| `reason_code` | `string` | reason code |
| `created_at` | `string` | created at |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |
| `currency` | `string` | currency |

## approvals

Primary key: `approval_id`. Classification: `RELATIONSHIP_SHARED`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `approval_id` | `string` | approval id; stable foreign/entity identifier |
| `case_id` | `string` | case id; stable foreign/entity identifier |
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `offer_version` | `int64` | offer version |
| `approver_org_id` | `string` | approver org id; stable foreign/entity identifier |
| `approver_principal_id` | `string` | approver principal id; stable foreign/entity identifier |
| `approval_role` | `string` | approval role |
| `decision` | `string` | decision |
| `decision_at` | `string` | decision at |
| `exact_terms_digest` | `string` | exact terms digest |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## negotiation_events

Primary key: `event_id`. Classification: `PLATFORM_AUDIT_RESTRICTED`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `event_id` | `string` | event id; stable foreign/entity identifier |
| `case_id` | `string` | case id; stable foreign/entity identifier |
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `sequence` | `int64` | sequence |
| `state` | `string` | state |
| `offer_id` | `string` | offer id; stable foreign/entity identifier |
| `offer_version` | `int64` | offer version |
| `actor_org_id` | `string` | actor org id; stable foreign/entity identifier |
| `at` | `string` | at |
| `terms_digest` | `string` | terms digest |
| `snapshot_version` | `double` | snapshot version |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## supplier_shareable_offers

Primary key: `offer_id`. Classification: `RELATIONSHIP_SHARED`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `offer_id` | `string` | offer id; stable foreign/entity identifier |
| `relationship_id` | `string` | relationship id; stable foreign/entity identifier |
| `lane_id` | `string` | lane id; stable foreign/entity identifier |
| `tenant_id` | `string` | tenant id; stable foreign/entity identifier |
| `week_start` | `string` | week start; Monday YYYY-MM-DD |
| `additional_qty_offer` | `int64` | additional qty offer |
| `premium_price_eur_per_unit` | `decimal128(20, 2)` | premium price eur per unit; Decimal EUR, not a float |
| `earliest_release_week` | `string` | earliest release week; Monday YYYY-MM-DD |
| `new_payment_days` | `int64` | new payment days |
| `expiry_at` | `string` | expiry at |
| `shared_with_buyer` | `bool` | shared with buyer |
| `extra_shift_hours` | `decimal128(20, 6)` | extra shift hours |
| `physical_input_snapshot_id` | `string` | physical input snapshot id; stable foreign/entity identifier |
| `earliest_production_start` | `string` | earliest production start |
| `id` | `string` | id |
| `buyer_tenant_id` | `string` | buyer tenant id; stable foreign/entity identifier |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |
| `currency` | `string` | currency |

## supplier_user_roles

Primary key: `principal_id, tenant_scope`. Classification: `PLATFORM_AUDIT_RESTRICTED`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `principal_id` | `string` | principal id; stable foreign/entity identifier |
| `org_id` | `string` | org id; stable foreign/entity identifier |
| `tenant_scope` | `string` | tenant scope |
| `role` | `string` | role |
| `active` | `bool` | active |
| `id` | `string` | id |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## graph_edges

Primary key: `edge_id`. Classification: `PLATFORM_AUDIT_RESTRICTED`.

| Field | Arrow type | Meaning / constraint |
|---|---|---|
| `edge_id` | `string` | edge id; stable foreign/entity identifier |
| `source_node_id` | `string` | source node id; stable foreign/entity identifier |
| `target_node_id` | `string` | target node id; stable foreign/entity identifier |
| `edge_type` | `string` | edge type |
| `tenant_scope` | `string` | tenant scope |
| `relationship_id` | `string` | relationship id; stable foreign/entity identifier |
| `edge_classification` | `string` | edge classification |
| `direction` | `string` | direction |
| `id` | `string` | id |
| `owner_org_id` | `string` | owner org id; stable foreign/entity identifier |
| `classification` | `string` | classification |
| `data_classification` | `string` | data classification |
| `schema_version` | `string` | schema version |
| `record_version` | `int64` | record version |
| `source_system` | `string` | source system |
| `source_record_id` | `string` | source record id; stable foreign/entity identifier |
| `source_updated_at` | `string` | source updated at |
| `ingested_at` | `string` | ingested at |
| `valid_from` | `string` | valid from |
| `valid_to` | `string` | Exclusive validity endpoint |

## Demand, stock and resource assumptions

Hierarchical demand combines segment base, lognormal product mix, plant and family factors, smooth seasonality, common market shock, segment noise, and selected 25% surges. Supplier segment/size proportions are explicit targets. Sourcing uses compatible segment/tenant pools and activates every authorized relationship. Every part has exactly one consuming plant; BOM edges describe independent same-plant subsets and increase in part ID, proving acyclicity. Parts with BOM parents are separately forecast manufacturing inputs; do not sum forecast and exploded demand without selecting a demand policy.

Lane capacities are contractual offered ceilings, never additive physical machine capacity. Unmapped lanes have independent contractual ceilings. Mapped lanes consume shared hours, with 10% reserved external work and explicit additional-shift flexibility. Resource stress is reported as a physical-capacity proxy. Purchase orders are samples of confirmed future incoming work, not a complete replenishment plan; remaining planning supply is uncommitted production and must be lead-time constrained by the engine. Only CONFIRMED future receipts enter baseline incoming inventory; no RECEIVED stock is counted twice.

## Scenario snapshots and lineage

Each case JSON is an immutable scoped numerical snapshot, with baseline table hashes, actual network IDs, explicit overrides and a snapshot digest. They are scenario inputs, not blanket edits of the generated baseline. Full snapshots involving raw machine hours are supplier internal. Buyer APIs must apply policy projections. Oracles are calculated with integer MILP and independent equal-hours capacity bounds. Multi-buyer cases require an authorized platform computation over locked scopes, and must not expose other buyers' demand. Mock connectors are illustrative formats with documented reverse mappings.
