"""VRM-side forked copies of Dimensionador modules victron/vrm_api still need
(Phase 3 of the Dimensionador/VRM Monitor split — see the plan's "Shared-module
strategy"). Dimensionador keeps its own originals unchanged; these are
deliberate, literal duplicates, not a shared package — see each module's own
docstring for why.

Lives inside victron/ specifically so it moves automatically when victron/ is
copied wholesale into its own repo (Phase 5): nothing extra to relocate then.
"""
