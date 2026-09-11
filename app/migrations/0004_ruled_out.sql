-- A listing you have decided against, without pretending you never found it.
--
-- `active = 0` already existed but means "gone": it disappears from the board and
-- takes its price history with it. That is wrong for a listing that is real, correctly
-- recorded, and simply not one you will buy from. Crowdshop is the case that forced
-- this: $869 is genuinely the cheapest number anyone has advertised, but it is a
-- group-buy whose freight is only costed after the purchase closes, so it can never
-- become a delivered price. Deactivating it would have hidden the cheapest price on
-- the board with no explanation; leaving it alone had the board nominating a price
-- that had been rejected.
--
-- So: ruled out stays visible and stays plotted, but never wins. The reason travels
-- with it, because "why did we discount this" is the question a future session asks.
ALTER TABLE listings ADD COLUMN ruled_out INTEGER NOT NULL DEFAULT 0;
ALTER TABLE listings ADD COLUMN ruled_out_reason TEXT;
ALTER TABLE listings ADD COLUMN ruled_out_at TEXT;
