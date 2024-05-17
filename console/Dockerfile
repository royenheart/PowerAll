FROM python:3.9-alpine

USER root
WORKDIR /root/frontend
RUN pip3 install -i https://mirrors.cernet.edu.cn/pypi/web/simple dash Requests PyYAML && \
    mkdir /etc/frontend
COPY assets /root/frontend
COPY main.py /root/frontend
ENV SERVER 0.0.0.0
ENV PORT 8085
CMD ["sh", "-c", "python3 main.py --server=${SERVER} --port=${PORT} --config-path=/etc/frontend"]

LABEL \
    author="RoyenHeart" \
    description="PowerAll Frontend" \
    license="AGPL v3"