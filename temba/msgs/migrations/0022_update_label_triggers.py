# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


# language=SQL
TRIGGER_SQL = """
----------------------------------------------------------------------
-- Trigger procedure to update label count
----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_label_count() RETURNS TRIGGER AS $$
DECLARE
  is_visible BOOLEAN;
BEGIN
  -- label applied to message
  IF TG_OP = 'INSERT' THEN
    -- is this message visible
    SELECT msgs_msg.visibility = 'V' INTO STRICT is_visible FROM msgs_msg WHERE msgs_msg.id = NEW.msg_id;

    IF is_visible THEN
      UPDATE msgs_label SET "count" = "count" + 1, visible_count = visible_count + 1 WHERE id = NEW.label_id;
    ELSE
      UPDATE msgs_label SET "count" = "count" + 1 WHERE id = NEW.label_id;
    END IF;

  -- label removed from message
  ELSIF TG_OP = 'DELETE' THEN
    -- is this message visible
    SELECT msgs_msg.visibility = 'V' INTO STRICT is_visible FROM msgs_msg WHERE msgs_msg.id = OLD.msg_id;

    IF is_visible THEN
      UPDATE msgs_label SET "count" = "count" - 1, visible_count = visible_count - 1 WHERE id = OLD.label_id;
    ELSE
      UPDATE msgs_label SET "count" = "count" - 1 WHERE id = OLD.label_id;
    END IF;

  -- no more labels for any messages
  ELSIF TG_OP = 'TRUNCATE' THEN
    UPDATE msgs_label SET "count" = 0, visible_count = 0;

  END IF;

  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- install for INSERT and DELETE on msgs_msg_labels
DROP TRIGGER IF EXISTS when_label_inserted_or_deleted_then_update_count_trg ON msgs_msg_labels;
CREATE TRIGGER when_label_inserted_or_deleted_then_update_count_trg
   AFTER INSERT OR DELETE ON msgs_msg_labels
   FOR EACH ROW EXECUTE PROCEDURE update_label_count();

-- install for TRUNCATE on msgs_msg_labels
DROP TRIGGER IF EXISTS when_labels_truncated_then_update_count_trg ON msgs_msg_labels;
CREATE TRIGGER when_labels_truncated_then_update_count_trg
  AFTER TRUNCATE ON msgs_msg_labels
  EXECUTE PROCEDURE update_label_count();

----------------------------------------------------------------------
-- Toggle a system label on a message
----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION
  msg_toggle_system_label(_msg_id INT, _org_id INT, _label_type CHAR(1), _add BOOLEAN)
RETURNS VOID AS $$
DECLARE
  _label_id INT;
BEGIN
  -- lookup the label id
  SELECT id INTO STRICT _label_id FROM msgs_label
  WHERE org_id = _org_id AND label_type = _label_type;

  -- don't do anything if label doesn't exist for some inexplicable reason
  IF _label_id IS NULL THEN
    RETURN;
  END IF;

  IF _add THEN
    BEGIN
      INSERT INTO msgs_msg_labels (label_id, msg_id) VALUES (_label_id, _msg_id);
    EXCEPTION WHEN unique_violation THEN
      -- do nothing
    END;
  ELSE
    DELETE FROM msgs_msg_labels WHERE label_id = _label_id AND msg_id = _msg_id;
  END IF;
END;
$$ LANGUAGE plpgsql;

----------------------------------------------------------------------
-- Convenience method to call msg_toggle_system_label with a row
----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION
  msg_toggle_system_label(_msg msgs_msg, _label_type CHAR(1), _add BOOLEAN)
RETURNS VOID AS $$
BEGIN
  PERFORM msg_toggle_system_label(_msg.id, _msg.org_id, _label_type, _add);
END;
$$ LANGUAGE plpgsql;

----------------------------------------------------------------------
-- Increment a system label's count
----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION
  increment_system_label(_org_id INT, _label_type CHAR(1), delta INT)
RETURNS VOID AS $$
BEGIN
  UPDATE msgs_label SET "count" = "count" + delta WHERE org_id = _org_id AND label_type = _label_type;
END;
$$ LANGUAGE plpgsql;

----------------------------------------------------------------------
-- Trigger procedure to update message system labels on column changes
----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_msg_system_labels() RETURNS TRIGGER AS $$
BEGIN
  -- new message added
  IF TG_OP = 'INSERT' THEN
    IF NEW.direction = 'I' THEN
      IF NEW.visibility = 'V' THEN
        IF NEW.msg_type = 'I' THEN
          PERFORM msg_toggle_system_label(NEW, 'I', true);
        ELSIF NEW.msg_type = 'F' THEN
          PERFORM msg_toggle_system_label(NEW, 'W', true);
        END IF;
      ELSIF NEW.visibility = 'A' THEN
        PERFORM msg_toggle_system_label(NEW, 'A', true);
      END IF;
    ELSIF NEW.direction = 'O' THEN
      IF NEW.status = 'Q' THEN
        PERFORM msg_toggle_system_label(NEW, 'O', true);
      ELSIF NEW.status = 'S' THEN
        PERFORM increment_system_label(NEW.org_id, 'S', 1);
      ELSIF NEW.status = 'F' THEN
        PERFORM msg_toggle_system_label(NEW, 'X', true);
      END IF;
    END IF;

  -- existing message updated
  ELSIF TG_OP = 'UPDATE' THEN
    -- TODO

  END IF;

  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- install for INSERT and UPDATE on msgs_msg
DROP TRIGGER IF EXISTS when_msgs_changed_then_update_labels_trg ON msgs_msg;
CREATE TRIGGER when_msgs_changed_then_update_labels_trg
  AFTER INSERT OR UPDATE ON msgs_msg
  FOR EACH ROW EXECUTE PROCEDURE update_msg_system_labels();

----------------------------------------------------------------------
-- Trigger procedure to update label counts on visibility changes
----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_msg_label_visible_counts() RETURNS TRIGGER AS $$
BEGIN
  -- is being archived or deleted (i.e. no longer visible)
  IF OLD.visibility = 'V' AND NEW.visibility != 'V' THEN
    UPDATE msgs_label SET visible_count = visible_count - 1
    FROM msgs_msg_labels
    WHERE msgs_msg_labels.label_id = msgs_label.id AND msgs_msg_labels.msg_id = NEW.id;
  END IF;

  -- is being restored (i.e. becoming visible)
  IF OLD.visibility != 'V' AND NEW.visibility = 'V' THEN
    UPDATE msgs_label SET visible_count = visible_count + 1
    FROM msgs_msg_labels
    WHERE msgs_msg_labels.label_id = msgs_label.id AND msgs_msg_labels.msg_id = NEW.id;
  END IF;

  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- install for UPDATE on msgs_msg
DROP TRIGGER IF EXISTS when_msg_updated_then_update_label_counts_trg ON msgs_msg;
CREATE TRIGGER when_msg_updated_then_update_label_counts_trg
  AFTER UPDATE OF visibility ON msgs_msg
  FOR EACH ROW EXECUTE PROCEDURE update_msg_label_visible_counts();

-- no longer used
DROP TRIGGER IF EXISTS when_msg_updated_then_update_label_counts_trg ON msgs_msg;
DROP FUNCTION IF EXISTS update_msg_user_label_counts();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('msgs', '0021_system_label_types'),
    ]

    operations = [
        migrations.RunSQL(TRIGGER_SQL)
    ]
