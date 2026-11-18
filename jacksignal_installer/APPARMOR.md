# AppArmor del instalador de JackSignal

El perfil propio protege la **aplicación instaladora**, con protección activada
y modo enforce. La integración de audio se ejecuta dentro de Home Assistant
Core: este perfil no limita FFmpeg, PulseAudio, voz, Alarmo o DLNA de Core.
No se han añadido privilegios ni cambiado las salidas de audio.

El instalador puede leer Python y `/installer`, comprobar `configuration.yaml`
y reemplazar únicamente `custom_components/jacksignal`. También puede crear
`.jacksignal-stage-*` y conservar/restaurar `.jacksignal-previous`. No tiene
acceso a red ni a un shell. No puede modificar `configuration.yaml`, `.storage`
u otras integraciones. Se mantiene `boot: manual_only`: instalar o actualizar
el código sigue requiriendo iniciar el instalador y reiniciar Core cuando proceda.

## Ensayo antes de publicar

Utiliza `jacksignal_installer_apparmor_lab` sin montar la configuración real de
Core. La imagen de laboratorio incorpora una configuración ficticia y un
proceso de espera para inspeccionar el perfil después del instalador. Crea la
versión anterior ficticia en la capa escribible del contenedor: un directorio
incrustado en la capa inferior de OverlayFS puede devolver EXDEV al renombrarlo,
lo cual no representa el montaje real de Core.

Ejecuta `python scripts/check_apparmor.py --confirm-disposable-lab` dentro del contenedor.
Llama al instalador real, comprueba instalación/actualización repetible y versión
anterior, y prueba denegaciones de secretos, otras integraciones, shell y red.
Comprueba por separado los casos de recuperación y rollback de `tests/test_installer.py`
y las suites de audio, voz, Alarmo, prioridades, historial y DLNA en las dos
arquitecturas. Una prueba sin altavoz físico no acredita sonido audible.

No desactives la protección para conseguir que pase. Comprueba el perfil efectivo
del proceso y `apparmor: profile` en Supervisor. [La puntuación oficial](https://contributors.home-assistant.io/apps/reference/security-rating/)
puede alcanzar 8/8 en esta aplicación sin puertos ni privilegios adicionales.

## ABI de la política

Se declara `abi <abi/3.0>,` explícitamente. En HAOS 18.4 con parser 3.1.7, omitirlo puede dejar sin mediar las reglas de red aunque el perfil figure en enforce. Las pruebas incluyen permisos efectivos, no solo la puntuación. No retires esa declaración ni desactives la protección para evitar una denegación.

## Resultado de esta entrega (0.19.2)

El 18 de noviembre de 2026 se instaló el complemento desechable en HAOS 18.4,
amd64 y aarch64, con Supervisor 2026.11.0 y Core 2026.11.2. En ambas VM el perfil
estaba en enforce, la protección activada y la puntuación instalada era 8/8.
El instalador real actualizó una versión ficticia 0.0.1, repitió la operación y
conservó su copia anterior. Se denegaron las lecturas de secretos de Core, la
modificación de otra integración y configuration.yaml, el shell y los sockets.

La suite de integración pasó sus **108 casos en cada arquitectura** (un caso
opcional PulseAudio omitido), en contenedores nativos con la versión real
de Core del laboratorio; incluye instalación y rollback, configuración, voz,
prioridades, Alarmo, historial, DLNA y FFmpeg. El ensayo opcional de salida
PulseAudio a un sumidero silencioso necesita activación y se declara por separado:
no se cambia el audio del Core del usuario ni se acredita un altavoz físico.
Las 17 pruebas Node del panel pasaron. Ruff y sintaxis de los publicadores
correctos; el publicador exige el perfil y este documento antes de copiar la app.

## Ejecutar el ayudante desde el clon

Sustituye `haos-lab` por el acceso SSH de tu laboratorio y prepara primero la
instalación desechable descrita arriba. El código se envía por stdin a Python;
no necesita permiso de ejecución sobre archivos del contenedor:

```sh
ssh root@haos-lab \
  'docker exec -i app_local_jacksignal_installer_apparmor_lab python - --confirm-disposable-lab' \
  < scripts/check_apparmor.py
```
