# vi: set ft=dockerfile :


FROM ubuntu:xenial
MAINTAINER Sergey Arkhipov <sarkhipov@mirantis.com>


ENV LC_ALL C.UTF-8
ENV LANG C.UTF-8


RUN set -x \
  && apt-get update \
  && apt-get install -y --no-install-recommends \
    python3 \
    python3-setuptools \
    wget \
  && wget --no-check-certificate https://github.com/Yelp/dumb-init/releases/download/v1.1.3/dumb-init_1.1.3_amd64.deb \
  && dpkg -i dumb-init_1.1.3_amd64.deb \
  && rm dumb-init_*.deb \
  && apt-get clean \
  && apt-get purge -y wget \
  && apt-get autoremove -y \
  && rm -r /var/lib/apt/lists/*


COPY output/eggs /eggs
COPY constraints.txt /constraints.txt


RUN set -x \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      gcc \
      libyaml-0-2 \
      libyaml-dev \
      python3-dev \
      python3-pip \
      python3-wheel \
    && pip3 install --no-cache-dir --disable-pip-version-check -c /constraints.txt /eggs/cephlcmlib*.tar.gz \
    && pip3 install --no-cache-dir --disable-pip-version-check -c /constraints.txt /eggs/cephlcm-common*.tar.gz \
    && pip3 install --no-cache-dir --disable-pip-version-check -c /constraints.txt /eggs/cephlcm-server-discovery*.tar.gz \
    && rm -r /eggs /constraints.txt \
    && apt-get clean \
    && apt-get purge -y libyaml-dev gcc python3-dev python3-pip \
    && apt-get autoremove -y \
    && rm -r /var/lib/apt/lists/*
