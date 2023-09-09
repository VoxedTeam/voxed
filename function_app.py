# MIT License

# Copyright (c) 2023 Voxed Team

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


import azure.functions as func
import logging

import os
from PIL import Image
import cv2
import numpy as np
import xed_reader
import random
import string
import tempfile
from io import BytesIO
from urllib.parse import quote
import shutil


app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

@app.route(route="XedDecode", methods=["POST"])
def XedDecode(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    # If xed file not passed correctly, returns 400
    if "file" not in req.files:
        print("File not received")
        return func.HttpResponse(
            "Xed file not passed in request body as value of \"file\" key",
            status_code=400
        )
    else:
        print("File received")

    # Get the xed file from req body
    file = req.files["file"]

    # Generates string to use on paths
    random_string = ''.join(random.choice(string.ascii_lowercase) for _ in range(8))
    image_folder_path = os.path.join(tempfile.gettempdir(), random_string)
    print("Random string: " + random_string)

    while os.path.exists(image_folder_path):
        random_string = ''.join(random.choice(string.ascii_lowercase) for _ in range(8))
        image_folder_path = os.path.join(tempfile.gettempdir(), random_string)

    # Creates folder for the decoded images
    try:
        os.mkdir(image_folder_path)
    except Exception as e:
        print(e)
        remove_files(img_folder_path=image_folder_path)
        return func.HttpResponse(
            f"Unexpected server error",
            status_code=500
        )

    # Saves the xed file temporarily
    xed_temp_filename = os.path.join(tempfile.gettempdir(),f"{random_string}.xed")

    try:
        file.save(xed_temp_filename)
    except Exception as e:
        print(e)
        remove_files(xed_path=xed_temp_filename,
                    img_folder_path=image_folder_path)

        return func.HttpResponse(
            f"Unexpected server error",
            status_code=500
        )
    
    # Extract the images from the xed file
    try:
        xed_reader.xed_decode(xed_temp_filename, image_folder_path, verbose=False)

    except Exception as e:
        print(e)
        remove_files(xed_path=xed_temp_filename,
                        img_folder_path=image_folder_path)

        return func.HttpResponse(
            "Error decoding file",
            status_code=500
        )
    
    print(f"{random_string}.xed decoded")
    
    # Generates a zip with the extracted images
    try:
        zip_path = os.path.join(tempfile.gettempdir(),random_string)
        shutil.make_archive(zip_path, 'zip', image_folder_path)
    except Exception as e:
        print(e)
        remove_files(xed_path=xed_temp_filename,
                        img_folder_path=image_folder_path,
                        zip_path=zip_path+".zip")
        return func.HttpResponse(
            f"Unexpected server error",
            status_code=500
        )
    
    print(random_string+".zip created")

    # Generates the bytestream that will be returned
    try:
        with open(zip_path+".zip", 'rb') as zip_file:
            zip_data = zip_file.read()
    except Exception as e:
        print(e)
        remove_files(xed_path=xed_temp_filename,
                        img_folder_path=image_folder_path,
                        zip_path=zip_path+".zip")
        return func.HttpResponse(
            f"Unexpected server error",
            status_code=500
        )
    
    # Delete temporary files
    remove_files(xed_path=xed_temp_filename,
                img_folder_path=image_folder_path,
                zip_path=zip_path+".zip")

    # Returns the bytestream
    return func.HttpResponse(
        zip_data,
        status_code=200,
        mimetype="application/zip",
        headers={"Content-Disposition": f"attachment;filename=images.zip"}
    )


def remove_files(xed_path=None, img_folder_path=None, zip_path=None):
    if(xed_path != None and os.path.isfile(xed_path)):
        os.remove(xed_path)
        print(f"{xed_path} deleted")

    if(img_folder_path != None and os.path.isdir(img_folder_path)):
        shutil.rmtree(img_folder_path)
        print(f"{img_folder_path} deleted")

    if(zip_path != None and os.path.isfile(zip_path)):
        os.remove(zip_path)
        print(f"{img_folder_path} deleted")
