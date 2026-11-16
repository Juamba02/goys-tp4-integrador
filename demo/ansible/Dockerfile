# Nodo de control de Ansible del MiniSOC-IA.
#
# Ansible no corre nativo en Windows, así que corre acá: un contenedor descartable,
# fuera de las redes del laboratorio, que maneja el Docker de la notebook por su
# socket. Ningún contenedor del laboratorio tiene acceso al socket.
#
# Se construye una vez con Internet (ejecutar.sh lo hace solo). Después funciona offline.
FROM docker:28.3.3-cli

RUN apk add --no-cache bash python3 ansible-core \
 && ansible-galaxy collection install --collections-path /usr/share/ansible/collections \
        community.docker:==5.4.0

ENV ANSIBLE_HOME=/tmp/ansible \
    ANSIBLE_LOCAL_TEMP=/tmp/ansible/tmp \
    ANSIBLE_COLLECTIONS_PATH=/usr/share/ansible/collections

ENTRYPOINT ["ansible-playbook"]
