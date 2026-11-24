-- Only the database holds the project seed. Clients receive one user's ten-minute key.
create table tebb_private.mobile_lan_seed (
    singleton boolean primary key check (singleton),
    seed bytea not null
);
revoke all on tebb_private.mobile_lan_seed from public, anon, authenticated;
insert into tebb_private.mobile_lan_seed values (true, uuid_send(gen_random_uuid()) || uuid_send(gen_random_uuid()));

create function public.tebb_mobile_lan_lease() returns jsonb
language sql stable security definer set search_path = '' as $$
    with epoch as (select floor(extract(epoch from now()) / 600)::bigint as n)
    select jsonb_build_object('user_id', auth.uid(), 'expires_at', (n + 1) * 600,
        'key', encode(sha256(seed || uuid_send(auth.uid()) || int8send(n)), 'hex'))
    from tebb_private.mobile_lan_seed, epoch where auth.uid() is not null
$$;
revoke all on function public.tebb_mobile_lan_lease() from public, anon;
grant execute on function public.tebb_mobile_lan_lease() to authenticated;
