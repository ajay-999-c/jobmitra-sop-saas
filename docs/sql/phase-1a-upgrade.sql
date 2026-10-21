BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001_company_management

CREATE TABLE companies (
    id UUID NOT NULL, 
    company_name TEXT NOT NULL, 
    company_name_key TEXT NOT NULL, 
    general_phone_numbers TEXT[] DEFAULT '{}'::text[] NOT NULL, 
    address_line TEXT, 
    city TEXT, 
    state TEXT, 
    postal_code TEXT, 
    source_register_ids TEXT[] DEFAULT '{}'::text[] NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_companies PRIMARY KEY (id), 
    CONSTRAINT uq_companies_company_name_key UNIQUE (company_name_key), 
    CONSTRAINT ck_companies_name_nonblank CHECK (length(btrim(company_name)) > 0), 
    CONSTRAINT ck_companies_key_nonblank CHECK (length(btrim(company_name_key)) > 0), 
    CONSTRAINT ck_companies_phones_no_null_elements CHECK (array_position(general_phone_numbers, NULL) IS NULL), 
    CONSTRAINT ck_companies_sources_no_null_elements CHECK (array_position(source_register_ids, NULL) IS NULL)
);

CREATE TABLE company_contacts (
    id UUID NOT NULL, 
    company_id UUID NOT NULL, 
    contact_name TEXT, 
    designation TEXT, 
    phone_numbers TEXT[] DEFAULT '{}'::text[] NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_company_contacts PRIMARY KEY (id), 
    CONSTRAINT fk_company_contacts_company FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE RESTRICT, 
    CONSTRAINT ck_company_contacts_phones_no_null_elements CHECK (array_position(phone_numbers, NULL) IS NULL)
);

CREATE INDEX ix_company_contacts_company_id ON company_contacts (company_id);

INSERT INTO alembic_version (version_num) VALUES ('0001_company_management') RETURNING alembic_version.version_num;

COMMIT;

