# Use the Java 8 WebSphere Liberty image (Acme Air requires Java 8 / Java EE 7)
FROM icr.io/appcafe/websphere-liberty:kernel-java8-openj9-ubi

ENV LICENSE=accept

USER root

# Download the Mongo Java Driver that Liberty requires
RUN mkdir -p /opt/ibm/wlp/usr/shared/resources/mongodb && \
    curl -o /opt/ibm/wlp/usr/shared/resources/mongodb/mongo-java-driver-2.12.2.jar -L https://repo1.maven.org/maven2/org/mongodb/mongo-java-driver/2.12.2/mongo-java-driver-2.12.2.jar && \
    chown -R 1001:0 /opt/ibm/wlp/usr/shared/resources/mongodb

USER 1001

# Copy the server configuration
COPY --chown=1001:0 server.xml /config/

# Copy the application binary into the apps folder
COPY --chown=1001:0 acmeair/acmeair-webapp/build/libs/acmeair-webapp-2.0.0-SNAPSHOT.war /config/apps/acmeair-webapp.war

# Run the utility script to install features declared in server.xml
RUN features.sh

# Generate a class cache to optimize container startup times
RUN configure.sh
