#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define REQ_BUF 2048

static volatile sig_atomic_t g_running = 1;

static void on_signal(int signo) {
    (void)signo;
    g_running = 0;
}

static int write_all(int fd, const void *buf, size_t len) {
    const char *p = (const char *)buf;
    while (len > 0) {
        ssize_t n = write(fd, p, len);
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        p += n;
        len -= (size_t)n;
    }
    return 0;
}

static void respond_text(int client, int code, const char *text) {
    char hdr[256];
    const char *reason = (code == 200) ? "OK" : (code == 404 ? "Not Found" : "Internal Server Error");
    int n = snprintf(hdr, sizeof(hdr),
        "HTTP/1.1 %d %s\r\n"
        "Content-Type: text/plain\r\n"
        "Content-Length: %zu\r\n"
        "Connection: close\r\n\r\n",
        code, reason, strlen(text));

    if (n > 0) {
        write_all(client, hdr, (size_t)n);
        write_all(client, text, strlen(text));
    }
}

static void respond_file(int client, const char *path) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) {
        respond_text(client, 404, "no frame\n");
        return;
    }

    struct stat st;
    if (fstat(fd, &st) < 0 || st.st_size <= 0) {
        close(fd);
        respond_text(client, 404, "empty frame\n");
        return;
    }

    char hdr[256];
    int n = snprintf(hdr, sizeof(hdr),
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: image/jpeg\r\n"
        "Content-Length: %lld\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n\r\n",
        (long long)st.st_size);

    if (n > 0) {
        if (write_all(client, hdr, (size_t)n) < 0) {
            close(fd);
            return;
        }
    }

    char buf[8192];
    while (1) {
        ssize_t r = read(fd, buf, sizeof(buf));
        if (r < 0) {
            if (errno == EINTR) {
                continue;
            }
            break;
        }
        if (r == 0) {
            break;
        }
        if (write_all(client, buf, (size_t)r) < 0) {
            break;
        }
    }

    close(fd);
}

int main(int argc, char **argv) {
    int port = 8080;
    const char *frame_path = "/run/picam/latest.jpg";

    int opt;
    while ((opt = getopt(argc, argv, "p:f:")) != -1) {
        switch (opt) {
            case 'p': port = atoi(optarg); break;
            case 'f': frame_path = optarg; break;
            default:
                fprintf(stderr, "usage: %s [-p port] [-f frame]\n", argv[0]);
                return 1;
        }
    }

    if (port <= 0 || port > 65535) {
        fprintf(stderr, "invalid port\n");
        return 1;
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);

    int server = socket(AF_INET, SOCK_STREAM, 0);
    if (server < 0) {
        perror("socket");
        return 1;
    }

    int yes = 1;
    setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons((uint16_t)port);

    if (bind(server, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind");
        close(server);
        return 1;
    }

    if (listen(server, 8) < 0) {
        perror("listen");
        close(server);
        return 1;
    }

    while (g_running) {
        int client = accept(server, NULL, NULL);
        if (client < 0) {
            if (errno == EINTR) {
                continue;
            }
            perror("accept");
            break;
        }

        char req[REQ_BUF];
        ssize_t n = read(client, req, sizeof(req) - 1);
        if (n <= 0) {
            close(client);
            continue;
        }
        req[n] = '\0';

        if (strncmp(req, "GET /health", 11) == 0) {
            respond_text(client, 200, "ok\n");
        } else if (strncmp(req, "GET /latest.jpg", 15) == 0) {
            respond_file(client, frame_path);
        } else {
            respond_text(client, 404, "not found\n");
        }

        close(client);
    }

    close(server);
    return 0;
}
