FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d \
    && chmod +x /usr/sbin/policy-rc.d \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates openssl postfix postsrsd python3 \
    && rm -rf /var/lib/apt/lists/* /etc/postsrsd.secret

COPY configure.py runtime.py /opt/mail-forwarder/

EXPOSE 25
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python3", "/opt/mail-forwarder/runtime.py", "healthcheck"]
ENTRYPOINT ["python3", "/opt/mail-forwarder/runtime.py"]
