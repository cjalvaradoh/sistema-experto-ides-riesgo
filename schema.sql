-- Base de hechos
CREATE TABLE eventos (
  id            BIGSERIAL PRIMARY KEY,
  usuario       TEXT NOT NULL,
  accion        TEXT NOT NULL,                 -- login, logout, leer_archivo, usar_sudo...
  objeto        TEXT,                          -- archivo o recurso
  host_origen   TEXT,
  resultado     TEXT NOT NULL DEFAULT 'exito', -- exito / fallo
  fecha_hora    TIMESTAMPTZ NOT NULL,
  etiqueta_real TEXT NOT NULL DEFAULT 'normal' -- normal / fuerza_bruta / etc. (solo para validar)
);

-- Perfiles estadísticos por usuario 
CREATE TABLE perfiles (
  usuario        TEXT NOT NULL,
  medida         TEXT NOT NULL,                -- ej. logins_por_hora
  n              INT NOT NULL DEFAULT 0,
  suma           DOUBLE PRECISION NOT NULL DEFAULT 0,
  suma_cuadrados DOUBLE PRECISION NOT NULL DEFAULT 0,
  PRIMARY KEY (usuario, medida)
);

-- Base de conocimientos
CREATE TABLE reglas (
  id          SERIAL PRIMARY KEY,
  nombre      TEXT UNIQUE NOT NULL,
  descripcion TEXT,
  condicion   JSONB NOT NULL,                  -- la definimos en la parte 3
  conclusion  TEXT NOT NULL,
  severidad   TEXT NOT NULL,                   -- baja / media / alta
  certeza     NUMERIC(3,2) NOT NULL DEFAULT 0.80,
  activa      BOOLEAN NOT NULL DEFAULT TRUE
);

-- Módulo de explicación
CREATE TABLE alertas (
  id          BIGSERIAL PRIMARY KEY,
  evento_id   BIGINT REFERENCES eventos(id),
  regla_id    INT REFERENCES reglas(id),
  origen      TEXT NOT NULL,                   -- regla / estadistico
  conclusion  TEXT NOT NULL,
  severidad   TEXT NOT NULL,
  certeza     NUMERIC(3,2),
  explicacion TEXT NOT NULL,
  creada_en   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_eventos_usuario_fecha ON eventos (usuario, fecha_hora);
   ALTER TABLE eventos ADD COLUMN incidente_id INT;

CREATE TABLE casos (
  id         SERIAL PRIMARY KEY,
  usuario    TEXT NOT NULL,
  inicio     TIMESTAMPTZ NOT NULL,
  fin        TIMESTAMPTZ NOT NULL,
  severidad  TEXT NOT NULL,
  certeza    NUMERIC(3,2) NOT NULL,
  fuentes    TEXT NOT NULL,   
  resumen    TEXT NOT NULL
);
ALTER TABLE alertas ADD COLUMN caso_id INT REFERENCES casos(id);