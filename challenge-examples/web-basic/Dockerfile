# Simple Web Challenge Example
FROM nginx:alpine

# Copy challenge files
COPY index.html /usr/share/nginx/html/
COPY flag.txt /usr/share/nginx/html/flag.txt

# Make flag harder to find
RUN chmod 644 /usr/share/nginx/html/flag.txt

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
