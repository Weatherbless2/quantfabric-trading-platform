FROM python:3.12-slim

WORKDIR /srv/quantfabric
COPY AuthAdminService/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY AuthAdminService /srv/quantfabric/AuthAdminService
ENV PYTHONPATH=/srv/quantfabric
CMD ["uvicorn", "AuthAdminService.app:app", "--host", "0.0.0.0", "--port", "18080"]
