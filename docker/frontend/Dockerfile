FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf

# Static files are mounted from ./frontend into /usr/share/nginx/html by docker-compose.
# For a baked-in build, copy them here instead:
# COPY . /usr/share/nginx/html

EXPOSE 80
