import os
import sys
import time
import shopify
import json
import requests
import mimetypes
import base64
from jmespath import search as jsearch
import re
from slugify import slugify

class ShopifyUploader:
    def __init__(self,token,site,apiVersion="2024-07"):
        
        self.key = token
        self.site = site
        self.uploaded = {}
        session = shopify.Session(f"{self.site}.myshopify.com/admin",apiVersion,token)
        shopify.ShopifyResource.activate_session(session)
        
    def version(self):
        return "12.3.24"
    def debug(self,message):
        if os.environ.get("SHOPIFY_UPLOADER_DEBUG","")=="yes":
            print(message,file=sys.stderr)
        
    def check_upload(self,filename,original_filename=None):
    
        if filename in self.uploaded:
            return self.uploaded[filename]
        if original_filename is not None and original_filename in self.uploaded:
            return self.uploaded[original_filename]
        
        result = json.loads(shopify.GraphQL().execute(
            """
            query GetFile($query:String) {
                files(first: 5, query: $query) {
                    nodes {
                        id
                        preview {
                            image {
                                url
                                id
                            }
                        }
                    }
                }
            }
            """,
            {"query":f'filename:"{filename}"'}
        ))
        
        
        if not 'data' in result:
            self.debug(json.dumps(result,indent=1))
        
        nodes = result['data']['files']['nodes']
        for node in nodes:
            if filename in node['preview']['image']['url']:
                self.uploaded[filename] = {
                    "url":node['preview']['image']['url'],
                    "id":node['id']
                }
                if original_filename is not None:
                    self.uploaded[original_filename] = self.uploaded[filename]    
                return self.uploaded[filename]    
        return None
    def checkUploadByID(self,fileId):
        res = json.loads(
            shopify.GraphQL().execute(
                """
                query getImage($query:String) {
                    files(first:5,query:$query) {
                        nodes {
                            createdAt
                            updatedAt
                            alt
                            ... on GenericFile {
                                id
                                originalFileSize
                                url
                            }
                            ... on MediaImage {
                                id
                                
                                image {
                                    id
                                    url
                                    width
                                    height
                                }
                            }
                        }
                    }
                }
                """,
                {
                    "query":f'id:{fileId.split("/")[-1]}'
                }
            )
        )
        
        if jsearch("data.files.nodes[0].image.url",res):
            return jsearch("data.files.nodes[0].image.url",res)
        return None
        
    
    
    def actual_filename(self,url):
        filename = url.split("?")[0].split("/")[-1]
        if filename in self.uploaded:
            return self.uploaded[filename]["url"]
        res = requests.head(url)
        filename = f'{".".join(filename.split(".")[0:-1])}{mimetypes.guess_extension(res.headers["Content-Type"])}'
        return filename
    def stripSizing(self,filename):    
        ret = "-".join(list(filter(lambda x: re.search(r'(\d+)x(\d+)',x) is None,re.split(r'[-_]',filename))))
        
        return ret
    
        
    def upload_image(self,url, alt="",check=True,resolution="REPLACE"):
        
        filename = self.actual_filename(url)
        self.debug(f"Uploading: {url} as {filename}")
        if filename in self.uploaded:
            return self.uploaded[filename]
        res = requests.head(url)
        
        filename = f'{self.stripSizing(".".join(list(map(lambda x:slugify(x),filename.split(".")[0:-1]))))}{mimetypes.guess_extension(res.headers["Content-Type"])}'
        

        uploaded = self.check_upload(filename,url.split("?")[0].split("/")[-1])
        if uploaded is not None:
            
            return uploaded
        upl = json.loads(shopify.GraphQL().execute(
            """
            mutation fileCreate($files: [FileCreateInput!]!) {
                fileCreate(files: $files) {
                    files {
                        preview {
                            image {
                                url 
                            }
                        } 
                        fileStatus
                        fileErrors {
                            code
                            details
                            message
                        }
                        id
                    } 
                } 
            }""",
            {
                'files': {
                    'alt': alt,
                    'contentType': 'IMAGE',
                    'originalSource': url,
                    'filename':filename.replace("jpeg","jpg"),
                    'duplicateResolutionMode':"REPLACE"
                }
            }
        ))
        
        
        file = jsearch("data.fileCreate.files[0]",upl)
        
        if file is None:
            print(json.dumps(upl,indent=2))
            print(url,filename)
            return None
        
        if not check:
            if file:
                return {"id":file.get("id")}
            
        
            
        if file.get("fileStatus")=="READY":
            details = {
                "url":jsearch("preview.image.url",file),
                "id":file.get('id')
            } 
            self.uploaded[filename] = details
            self.uploaded[url.split("?")[0].split("/")[-1]] = details
            return details
             
        if file.get("fileStatus")=="UPLOADED":
            attempts = 0
            while attempts<30:
                uploadedFile = self.checkUploadByID(file.get("id"))
                if uploadedFile is not None:
                    details = {
                        "url":uploadedFile,
                        "id":file.get('id')
                    }
                    self.uploaded[filename] = details
                    self.uploaded[url.split("?")[0].split("/")[-1]] = details
                    self.debug(f"Uploaded to {details['url']}")
                    return details
                else:
                    self.debug(f"retrying {filename} {attempts}")
                    time.sleep(1)
                    attempts = attempts+1
        else:
            return None
        