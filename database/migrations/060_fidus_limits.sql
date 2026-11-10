-- 060: Pylontech/Fidus battery limits from Oscar (2026-11-10): each Fidus charges at most 100 A, so the Mega fuse on the Lynx bar is 125 A.
-- Needs the batteries.max_charge_a / fuse_a columns from 058. Only fills what is empty.
UPDATE batteries SET max_charge_a = COALESCE(max_charge_a, 100), fuse_a = COALESCE(fuse_a, 125) WHERE model ILIKE 'Fidus%';
