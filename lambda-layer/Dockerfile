# # Dockerfile for building Lambda layer with Python 3.12 dependencies
# FROM public.ecr.aws/lambda/python:3.12

# # Set working directory
# WORKDIR /layer

# # Copy requirements and helper code
# COPY requirements.txt .
# COPY helper ./helper

# # Install Python dependencies to /layer/python (Lambda layer format)
# RUN pip install --upgrade pip && \
#     pip install -r requirements.txt -t python

# x86_64 Python 3.12 Lambda image
FROM public.ecr.aws/lambda/python:3.12

WORKDIR /opt

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt -t python

COPY helper ./python/helper

# Zip the layer
RUN zip -r /opt/lambda_layer.zip python