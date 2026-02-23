# Buffer Overflow Challenge
FROM ubuntu:22.04

# Install necessary tools
RUN apt-get update && \
    apt-get install -y gcc socat && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy source, binary, and flag
COPY vuln.c .
COPY vuln .
COPY flag.txt .

# Binary is pre-compiled locally for consistency

# Expose port
EXPOSE 1337

# Run socat to listen on port 1337 and spawn vuln on connection
CMD ["socat", "TCP-LISTEN:1337,fork", "EXEC:./vuln"]