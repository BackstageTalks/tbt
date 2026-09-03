begin;

create or replace function public.promote_model_version(
    p_model_version text,
    p_reason text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_now timestamptz := now();
    v_target public.model_versions%rowtype;
    v_previous_champion text;
begin
    if p_model_version is null
       or btrim(p_model_version) = '' then
        raise exception 'model version is required';
    end if;

    perform pg_advisory_xact_lock(
        hashtext('tbt-model-promotion')
    );

    select *
    into v_target
    from public.model_versions
    where model_version = p_model_version
    for update;

    if not found then
        raise exception
            'unknown model version: %',
            p_model_version;
    end if;

    if v_target.lifecycle_status = 'champion' then
        return jsonb_build_object(
            'model_version',
            p_model_version,
            'status',
            'champion',
            'changed',
            false
        );
    end if;

    if v_target.lifecycle_status <> 'challenger' then
        raise exception
            'only challenger can be promoted; current status=%',
            v_target.lifecycle_status;
    end if;

    select model_version
    into v_previous_champion
    from public.model_versions
    where lifecycle_status = 'champion'
    order by promoted_at desc nulls last
    limit 1
    for update;

    update public.model_versions
    set
        lifecycle_status = 'rejected',
        rejected_at = v_now,
        promotion_reason = coalesce(
            promotion_reason,
            'Superseded by ' || p_model_version
        )
    where lifecycle_status = 'champion'
      and model_version <> p_model_version;

    update public.model_versions
    set
        lifecycle_status = 'champion',
        promoted_at = v_now,
        rejected_at = null,
        promotion_reason = coalesce(
            p_reason,
            'Promoted after challenger evaluation'
        )
    where model_version = p_model_version;

    return jsonb_build_object(
        'model_version',
        p_model_version,
        'status',
        'champion',
        'changed',
        true,
        'previous_champion',
        v_previous_champion,
        'promoted_at',
        v_now
    );
end;
$$;

revoke all
on function public.promote_model_version(text, text)
from public;

grant execute
on function public.promote_model_version(text, text)
to service_role;

commit;
