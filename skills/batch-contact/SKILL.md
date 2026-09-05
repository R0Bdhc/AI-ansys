---
name: batch-contact
description: Batch-create ANSYS Mechanical contact pairs by matching Named Selection prefixes. Use for previewing or executing large contact-region setups in Mechanical 242+ with Bonded, Frictional, Frictionless, NoSeparation, or Rough contacts.
---

# Batch Contact

Create contact regions by pairing source and target Named Selections that share the same suffix.

## Collect inputs

Require `source_prefix` and `target_prefix`. Default `contact_type` to `Frictionless`, `contact_name_prefix` to `AUTO_CONTACT_`, and `launch` to `false`.

Match names after removing the two prefixes:

```text
NS_SRC_BOLT_01 + NS_TGT_BOLT_01 -> AUTO_CONTACT_BOLT_01
```

Accept only `Bonded`, `Frictional`, `Frictionless`, `NoSeparation`, or `Rough` as the contact type.

## Execute safely

1. Start in preview mode unless the user explicitly requests real execution.
2. Call the `ansys-local` MCP tool `mechanical_batch_contact` with the collected inputs.
3. For `launch=true`, first call `mechanical_status` and require Mechanical version 242 or newer.
4. Report paired selections and unmatched source or target suffixes.

Do not claim that contact regions were created when the tool returned only a script preview. Do not try to create missing Named Selections from geometry.

## Report

State the mode, prefixes, contact type, number of pairs, generated names, unmatched suffixes, Mechanical version, and any returned script or error.

## Knowledge lifecycle

Before substantial use or behavior changes, invoke `$knowledge-driven-skill-sync` to pull curated knowledge for `batch-contact` and read `references/knowledge.md` when present. After reusable learning or a capability update, record it and run the lifecycle sync before committing.
