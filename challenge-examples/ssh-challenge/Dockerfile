# SSH Access Challenge
FROM ubuntu:22.04

# Install SSH server
RUN apt-get update && \
    apt-get install -y openssh-server sudo && \
    rm -rf /var/lib/apt/lists/*

# Create CTF user
RUN useradd -m -s /bin/bash ctfuser && \
    echo 'ctfuser:weakpassword123' | chpasswd

# Add flag
RUN echo 'FLAG{ssh_4cc3ss_gr4nt3d}' > /home/ctfuser/flag.txt && \
    chown ctfuser:ctfuser /home/ctfuser/flag.txt && \
    chmod 400 /home/ctfuser/flag.txt

# Configure SSH
RUN mkdir /var/run/sshd && \
    echo 'PermitRootLogin no' >> /etc/ssh/sshd_config && \
    echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config

EXPOSE 22

CMD ["/usr/sbin/sshd", "-D"]
