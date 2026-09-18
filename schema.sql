-- Ejecutar en Supabase: SQL Editor -> New query -> Run

create table if not exists procesos (
  id                     bigint generated always as identity primary key,
  radicado               varchar(23) not null unique
                         check (radicado ~ '^[0-9]{23}$'),
  alias                  text,
  ultima_actuacion_fecha date,
  estado                 text not null default 'activo',
  created_at             timestamptz not null default now()
);

create table if not exists actuaciones (
  id               bigint generated always as identity primary key,
  proceso_id       bigint not null references procesos(id) on delete cascade,
  fecha_actuacion  date   not null,
  actuacion        text   not null,
  resumen_json     jsonb,
  notificado       boolean not null default false,
  created_at       timestamptz not null default now()
);

create index if not exists idx_actuaciones_proceso   on actuaciones (proceso_id, fecha_actuacion);
create index if not exists idx_actuaciones_pendiente on actuaciones (proceso_id) where notificado = false;
create index if not exists idx_procesos_estado       on procesos (estado);

-- Seguridad: el worker corre en tu servidor, así que usa la clave "service_role"
-- en SUPABASE_KEY (nunca en un frontend). Con RLS activo y sin políticas, la
-- clave anónima no podrá leer ni escribir estas tablas.
alter table procesos    enable row level security;
alter table actuaciones enable row level security;
