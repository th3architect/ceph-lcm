# vi: set ft=dockerfile :


FROM shrimp-base-plugins
MAINTAINER Sergey Arkhipov <sarkhipov@mirantis.com>


COPY output/eggs /eggs
COPY constraints.txt /constraints.txt
COPY containerization/files/uwsgi.ini /etc/shrimp-api-uwsgi.ini


RUN set -x \
  && apt-get update \
  && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libpcre3 \
    libpcre3-dev \
    python3-dev \
    python3-pip \
  && pip3 install --compile --no-cache-dir --disable-pip-version-check -c /constraints.txt uwsgi \
  && pip3 install --compile --no-cache-dir --disable-pip-version-check /eggs/shrimp_migrations*.whl \
  && pip3 install --compile --no-cache-dir --disable-pip-version-check /eggs/shrimp_api*.whl \
  && rm -r /eggs /constraints.txt \
  && apt-get clean \
  && apt-get purge -y libffi-dev libpcre3-dev python3-dev python3-pip gcc \
  && apt-get autoremove -y \
  && rm -r /var/lib/apt/lists/*


EXPOSE 8000

ENTRYPOINT ["/usr/bin/dumb-init", "-c", "--"]
CMD ["sh", "-c", "shrimp-migrations apply && uwsgi /etc/shrimp-api-uwsgi.ini"]
