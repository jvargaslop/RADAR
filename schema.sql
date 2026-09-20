-- =========================================================================
-- Claria Radar · Esquema multiusuario
-- Ejecutar en Supabase: SQL Editor -> New query -> Run
--
-- Este script se puede ejecutar varias veces sin problema.
-- =========================================================================

-- ---------------------------------------------------------------------------
-- 0) Migración: si existen las tablas de la versión personal (sin user_id),
--    se eliminan para recrearlas con el modelo multiusuario. Esos datos no
--    tienen dueño, así que no se pueden conservar. Si tus tablas ya son las
--    nuevas, este bloque no hace nada.
-- ---------------------------------------------------------------------------
do $$
begin
  if exists (select 1 from information_schema.tables
             where table_schema = 'public' and table_name = 'procesos')
     and not exists (select 1 from information_schema.columns
                     where table_schema = 'public' and table_name = 'procesos'
                       and column_name = 'user_id') then
    drop table if exists actuaciones cascade;
    drop table if exists procesos cascade;
  end if;
end
$$;

-- ---------------------------------------------------------------------------
-- 1) Perfiles: datos de WhatsApp y plan de cada cliente
-- ---------------------------------------------------------------------------
create table if not exists perfiles (
  user_id           uuid primary key references auth.users(id) on delete cascade,
  telefono          text,                          -- +573001234567
  callmebot_apikey  text,                          -- clave propia de cada cliente
  plan              text   not null default 'gratis',
  max_procesos      int    not null default 3,     -- límite del plan
  resumen_diario    boolean not null default true,  -- mensaje de las 8 a.m.
  created_at        timestamptz not null default now()
);

-- Para bases ya creadas antes de esta versión
alter table perfiles add column if not exists resumen_diario boolean not null default true;

-- Crea el perfil automáticamente cuando alguien se registra
create or replace function crear_perfil() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into perfiles (user_id) values (new.id) on conflict do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function crear_perfil();

-- Usuarios que ya existían antes de este esquema
insert into perfiles (user_id) select id from auth.users on conflict do nothing;

-- ---------------------------------------------------------------------------
-- 2) Procesos y actuaciones (cada proceso pertenece a un usuario)
-- ---------------------------------------------------------------------------
create table if not exists procesos (
  id                     bigint generated always as identity primary key,
  user_id                uuid not null default auth.uid()
                         references auth.users(id) on delete cascade,
  radicado               varchar(23) not null check (radicado ~ '^[0-9]{23}$'),
  alias                  text,
  despacho               text,   -- juzgado donde cursa
  partes                 text,   -- demandante / demandado
  clase_proceso          text,
  historial_cargado      boolean not null default false,  -- ya se guardó el historial inicial
  ultima_actuacion_fecha date,
  estado                 text not null default 'activo'
                         check (estado in ('activo', 'pausado')),
  created_at             timestamptz not null default now(),
  unique (user_id, radicado)   -- dos clientes pueden vigilar el mismo radicado
);

-- Para bases ya creadas antes de esta versión (no hace nada si las columnas existen)
alter table procesos add column if not exists despacho      text;
alter table procesos add column if not exists partes        text;
alter table procesos add column if not exists clase_proceso text;
alter table procesos add column if not exists historial_cargado boolean not null default false;

create table if not exists actuaciones (
  id               bigint generated always as identity primary key,
  proceso_id       bigint not null references procesos(id) on delete cascade,
  fecha_actuacion  date   not null,
  actuacion        text   not null,
  resumen_json     jsonb,
  notificado       boolean not null default false,
  created_at       timestamptz not null default now()
);

create index if not exists idx_procesos_user         on procesos (user_id);
create index if not exists idx_procesos_estado       on procesos (estado);
create index if not exists idx_actuaciones_proceso   on actuaciones (proceso_id, fecha_actuacion);
create index if not exists idx_actuaciones_pendiente on actuaciones (proceso_id) where notificado = false;
-- Blindaje contra duplicados aunque dos ciclos corran a la vez
create unique index if not exists uq_actuacion_unica
  on actuaciones (proceso_id, fecha_actuacion, md5(actuacion));

-- ---------------------------------------------------------------------------
-- 3) Límite de procesos por plan (se valida en la base de datos, no solo en la app)
-- ---------------------------------------------------------------------------
create or replace function validar_limite_procesos() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  limite   int;
  actuales int;
begin
  select max_procesos into limite from perfiles where user_id = new.user_id;
  select count(*) into actuales from procesos where user_id = new.user_id;
  if actuales >= coalesce(limite, 3) then
    raise exception 'LIMITE_PROCESOS: tu plan permite % procesos', coalesce(limite, 3);
  end if;
  return new;
end;
$$;

drop trigger if exists trg_limite_procesos on procesos;
create trigger trg_limite_procesos
  before insert on procesos
  for each row execute function validar_limite_procesos();

-- ---------------------------------------------------------------------------
-- 4) Seguridad: Row Level Security (cada usuario solo ve lo suyo)
-- ---------------------------------------------------------------------------
alter table perfiles    enable row level security;
alter table procesos    enable row level security;
alter table actuaciones enable row level security;

drop policy if exists perfiles_select on perfiles;
drop policy if exists perfiles_update on perfiles;
drop policy if exists procesos_propios on procesos;
drop policy if exists actuaciones_propias on actuaciones;

create policy perfiles_select on perfiles
  for select using (user_id = auth.uid());

create policy perfiles_update on perfiles
  for update using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy procesos_propios on procesos
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy actuaciones_propias on actuaciones
  for all
  using (exists (select 1 from procesos p where p.id = proceso_id and p.user_id = auth.uid()))
  with check (exists (select 1 from procesos p where p.id = proceso_id and p.user_id = auth.uid()));

-- El cliente solo puede editar su teléfono, su clave y si quiere el resumen diario; NUNCA su plan ni su límite
revoke all on perfiles from anon, authenticated;
grant select on perfiles to authenticated;
grant update (telefono, callmebot_apikey, resumen_diario) on perfiles to authenticated;

-- El worker usa la clave service_role, que ignora RLS. Nunca la pongas en la app web.

-- Recarga la caché de la API para que las tablas nuevas se vean de inmediato
notify pgrst, 'reload schema';
