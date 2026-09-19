"""One module per wizard step (PLAN_PHASE20_PROPOSALS_JINJA.md §1.2), mirroring
admin_*.py's granularity: webapp/blueprints/wizard.py owns routing/dispatch,
each module here owns one step's build_context()/persistence logic.
"""
