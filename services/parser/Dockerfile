ARG KAIROS_API_BASE_IMAGE
FROM ${KAIROS_API_BASE_IMAGE}
USER root
COPY services/parser/server.py services/parser/child.py /opt/kairos-parser/
RUN chmod 0555 /opt/kairos-parser/*.py
USER 10001:10001
WORKDIR /opt/kairos-parser
ENTRYPOINT ["python", "-I", "/opt/kairos-parser/server.py"]
