-- Upgrade installations that applied 001 before OIDC role snapshots existed.
-- In a fresh installation this statement is a no-op because 001 creates it.

ALTER TABLE auth_session
    ADD COLUMN IF NOT EXISTS oidc_roles JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Keycloak's realm role `admin` is mapped to the temporary Casbin subject
-- `role:admin` for each OIDC session. This bootstrap rule lets the first
-- production administrator manage the narrower account/project/fund policies.
INSERT INTO casbin_rule (ptype, v0, v1, v2, v3)
SELECT 'p', 'role:admin', 'desk:cn_equity', '*', '*'
WHERE NOT EXISTS (
    SELECT 1
    FROM casbin_rule
    WHERE ptype = 'p'
      AND v0 = 'role:admin'
      AND v1 = 'desk:cn_equity'
      AND v2 = '*'
      AND v3 = '*'
);
