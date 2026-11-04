-- Cloud-only boundary. No local files, chat history, credentials or tools API.
create schema if not exists extensions;
create extension if not exists vector with schema extensions;
grant usage on schema extensions to authenticated;
create schema tebb_private;
revoke all on schema tebb_private from public, anon, authenticated;
grant usage on schema tebb_private to authenticated;

create table tebb_private.personalization_heads (
    user_id uuid primary key references auth.users(id) on delete cascade,
    revision bigint not null default 0 check (revision >= 0)
);

create table tebb_private.personalization_records (
    user_id uuid not null references auth.users(id) on delete cascade,
    id uuid not null,
    kind text not null check (kind in ('profile', 'preference', 'memory')),
    category text not null check (category in ('communication', 'knowledge', 'goal', 'project', 'other')),
    text text,
    scope text not null check (scope in ('user', 'project', 'companion')),
    scope_id text not null check (length(scope_id) <= 128),
    source_device_id uuid,
    source_ref text check (length(source_ref) between 1 and 256),
    state text not null check (state in ('active', 'disabled', 'deleted')),
    version bigint not null check (version > 0),
    sequence bigint not null check (sequence > 0),
    confirmed_at timestamptz not null,
    updated_at timestamptz not null,
    primary key (user_id, id),
    unique (user_id, sequence),
    check ((scope = 'user' and scope_id = '') or (scope <> 'user' and length(btrim(scope_id)) > 0)),
    check ((state = 'deleted' and text is null and source_ref is null and source_device_id is null)
        or (state <> 'deleted' and length(btrim(text)) between 1 and 4000 and text is not null))
);

-- Receipts keep a request digest and metadata, never a copy of memory text.
create table tebb_private.personalization_operations (
    user_id uuid not null references auth.users(id) on delete cascade,
    id uuid not null,
    request_digest bytea not null,
    receipt jsonb not null,
    created_at timestamptz not null default now(),
    primary key (user_id, id)
);

alter table tebb_private.personalization_heads enable row level security;
alter table tebb_private.personalization_heads force row level security;
alter table tebb_private.personalization_records enable row level security;
alter table tebb_private.personalization_records force row level security;
alter table tebb_private.personalization_operations enable row level security;
alter table tebb_private.personalization_operations force row level security;

create policy own_head on tebb_private.personalization_heads for select to authenticated
    using (user_id = (select auth.uid()));
create policy own_record on tebb_private.personalization_records for select to authenticated
    using (user_id = (select auth.uid()));
create policy own_operation on tebb_private.personalization_operations for select to authenticated
    using (user_id = (select auth.uid()));
revoke all on all tables in schema tebb_private from public, anon, authenticated;
grant select on all tables in schema tebb_private to authenticated;

create function public.tebb_personalization_status() returns jsonb
language plpgsql stable security invoker set search_path = '' as $$
declare v_user uuid := auth.uid();
begin
    if v_user is null then raise exception 'authentication required' using errcode = '42501'; end if;
    return jsonb_build_object('contract', 'tebb.personalization.v2', 'user_id', v_user,
        'revision', coalesce((select revision from tebb_private.personalization_heads where user_id = v_user), 0),
        'pgvector', exists(select 1 from pg_catalog.pg_extension where extname = 'vector'));
end;
$$;

create function public.tebb_personalization_apply(
    p_operation_id uuid, p_record_id uuid, p_expected_version bigint,
    p_action text, p_payload jsonb default null
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare
    v_user uuid := auth.uid();
    v_head bigint;
    v_record tebb_private.personalization_records%rowtype;
    v_operation tebb_private.personalization_operations%rowtype;
    v_exists boolean;
    v_status text;
    v_digest bytea;
    v_receipt jsonb;
    v_scope text;
    v_scope_id text;
    v_time timestamptz;
begin
    if v_user is null then raise exception 'authentication required' using errcode = '42501'; end if;
    if p_operation_id is null or p_record_id is null or p_expected_version is null or p_expected_version < 0
        or p_action is null or p_action not in ('put', 'disable', 'delete') then
        raise exception 'invalid operation' using errcode = '22023';
    end if;
    if p_action = 'put' then
        if p_payload is null or jsonb_typeof(p_payload) <> 'object' then
            raise exception 'put requires a confirmed record' using errcode = '22023';
        end if;
        if p_payload - array['kind','category','text','scope','scope_id','source_device_id','source_ref'] <> '{}'::jsonb
            or not (p_payload ?& array['kind','category','text'])
            or jsonb_typeof(p_payload->'kind') <> 'string' or p_payload->>'kind' not in ('profile','preference','memory')
            or jsonb_typeof(p_payload->'category') <> 'string' or p_payload->>'category' not in ('communication','knowledge','goal','project','other')
            or jsonb_typeof(p_payload->'text') <> 'string' or length(btrim(p_payload->>'text')) not between 1 and 4000 then
            raise exception 'unsupported record fields' using errcode = '22023';
        end if;
        v_scope := coalesce(p_payload->>'scope', 'user');
        v_scope_id := coalesce(p_payload->>'scope_id', '');
        if v_scope not in ('user','project','companion') or length(v_scope_id) > 128
            or (v_scope = 'user' and v_scope_id <> '') or (v_scope <> 'user' and length(btrim(v_scope_id)) = 0)
            or (p_payload ? 'scope' and jsonb_typeof(p_payload->'scope') <> 'string')
            or (p_payload ? 'scope_id' and jsonb_typeof(p_payload->'scope_id') <> 'string')
            or (p_payload ? 'source_ref' and (jsonb_typeof(p_payload->'source_ref') <> 'string'
                or length(p_payload->>'source_ref') not between 1 and 256))
            or (p_payload ? 'source_device_id' and jsonb_typeof(p_payload->'source_device_id') <> 'string') then
            raise exception 'invalid record scope or source' using errcode = '22023';
        end if;
        -- Parse a supplied device ID before changing any state.
        perform (p_payload->>'source_device_id')::uuid;
    elsif p_payload is not null then
        raise exception 'disable/delete do not accept a payload' using errcode = '22023';
    end if;
    v_digest := sha256(convert_to(jsonb_build_object('record',p_record_id,'version',p_expected_version,
        'action',p_action,'payload',p_payload)::text, 'UTF8'));

    -- Per-user lock makes revisions follow commit order, including parallel devices.
    insert into tebb_private.personalization_heads(user_id) values (v_user) on conflict do nothing;
    select revision into v_head from tebb_private.personalization_heads where user_id = v_user for update;
    v_time := clock_timestamp();
    select * into v_operation from tebb_private.personalization_operations where user_id = v_user and id = p_operation_id;
    if found then
        if v_operation.request_digest <> v_digest then
            raise exception 'operation ID already used for a different request' using errcode = '22023';
        end if;
        return v_operation.receipt;
    end if;
    select * into v_record from tebb_private.personalization_records where user_id = v_user and id = p_record_id;
    v_exists := found;
    if v_exists and v_record.state = 'deleted' then v_status := 'gone';
    elsif (v_exists or p_action <> 'delete') and coalesce(v_record.version, 0) <> p_expected_version then v_status := 'conflict';
    elsif not v_exists and p_action = 'disable' then v_status := 'not_found';
    else
        v_status := 'applied';
        v_head := v_head + 1;
        if p_action = 'put' then
            insert into tebb_private.personalization_records
                (user_id,id,kind,category,text,scope,scope_id,source_device_id,source_ref,state,version,sequence,confirmed_at,updated_at)
            values (v_user,p_record_id,p_payload->>'kind',p_payload->>'category',p_payload->>'text',v_scope,v_scope_id,
                (p_payload->>'source_device_id')::uuid,p_payload->>'source_ref','active',coalesce(v_record.version,0)+1,v_head,v_time,v_time)
            on conflict (user_id,id) do update set kind=excluded.kind,category=excluded.category,text=excluded.text,
                scope=excluded.scope,scope_id=excluded.scope_id,source_device_id=excluded.source_device_id,
                source_ref=excluded.source_ref,state=excluded.state,version=excluded.version,sequence=excluded.sequence,
                confirmed_at=excluded.confirmed_at,updated_at=excluded.updated_at;
        elsif not v_exists then
            -- Retire an identity even when its earlier create is still in flight.
            -- No content or source is required or preserved by this fence.
            insert into tebb_private.personalization_records
                (user_id,id,kind,category,text,scope,scope_id,state,version,sequence,confirmed_at,updated_at)
            values (v_user,p_record_id,'memory','other',null,'user','','deleted',1,v_head,v_time,v_time);
        else
            update tebb_private.personalization_records set
                state=case when p_action='delete' then 'deleted' else 'disabled' end,
                text=case when p_action='delete' then null else text end,
                source_device_id=case when p_action='delete' then null else source_device_id end,
                source_ref=case when p_action='delete' then null else source_ref end,
                version=version+1,sequence=v_head,updated_at=v_time
            where user_id=v_user and id=p_record_id;
        end if;
        update tebb_private.personalization_heads set revision=v_head where user_id=v_user;
        select * into v_record from tebb_private.personalization_records where user_id=v_user and id=p_record_id;
    end if;
    v_receipt := jsonb_build_object('user_id',v_user,'operation_id',p_operation_id,'record_id',p_record_id,
        'status',v_status,'version',coalesce(v_record.version,0),'cursor',v_head,'action',p_action);
    insert into tebb_private.personalization_operations(user_id,id,request_digest,receipt) values(v_user,p_operation_id,v_digest,v_receipt);
    return v_receipt;
end;
$$;

create function public.tebb_personalization_operation(p_operation_id uuid) returns jsonb
language plpgsql stable security invoker set search_path = '' as $$
declare v_user uuid := auth.uid(); v_receipt jsonb;
begin
    if v_user is null then raise exception 'authentication required' using errcode = '42501'; end if;
    select receipt into v_receipt from tebb_private.personalization_operations where user_id=v_user and id=p_operation_id;
    return jsonb_build_object('user_id',v_user,'found',v_receipt is not null,'receipt',v_receipt);
end;
$$;

create function public.tebb_personalization_pull(p_after bigint default 0, p_limit integer default 100) returns jsonb
language plpgsql stable security invoker set search_path = '' as $$
declare v_user uuid := auth.uid(); v_head bigint; v_rows jsonb; v_more boolean; v_next bigint;
begin
    if v_user is null then raise exception 'authentication required' using errcode = '42501'; end if;
    select coalesce((select revision from tebb_private.personalization_heads where user_id=v_user),0) into v_head;
    if p_after is null or p_after < 0 or p_after > v_head or p_limit is null or p_limit not between 1 and 100 then
        raise exception 'invalid cursor or page size' using errcode = '22023';
    end if;
    select coalesce(jsonb_agg(to_jsonb(r) - 'user_id' order by r.sequence),'[]'::jsonb) into v_rows from (
        select * from tebb_private.personalization_records where user_id=v_user and sequence > p_after and sequence <= v_head
        order by sequence limit p_limit+1
    ) r;
    v_more := jsonb_array_length(v_rows) > p_limit;
    if v_more then
        v_rows := v_rows - p_limit;
        v_next := (v_rows->(p_limit-1)->>'sequence')::bigint;
    else v_next := v_head;
    end if;
    return jsonb_build_object('user_id',v_user,'records',v_rows,'cursor',v_next,'has_more',v_more,'head',v_head);
end;
$$;

revoke all on function public.tebb_personalization_status() from public, anon;
revoke all on function public.tebb_personalization_apply(uuid,uuid,bigint,text,jsonb) from public, anon;
revoke all on function public.tebb_personalization_operation(uuid) from public, anon;
revoke all on function public.tebb_personalization_pull(bigint,integer) from public, anon;
grant execute on function public.tebb_personalization_status() to authenticated;
grant execute on function public.tebb_personalization_apply(uuid,uuid,bigint,text,jsonb) to authenticated;
grant execute on function public.tebb_personalization_operation(uuid) to authenticated;
grant execute on function public.tebb_personalization_pull(bigint,integer) to authenticated;
