docker rmi --force poprox_web
docker image build --ssh default -t poprox_web .
docker tag poprox_web:latest 422240912951.dkr.ecr.us-east-1.amazonaws.com/poprox_web:latest

aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 422240912951.dkr.ecr.us-east-1.amazonaws.com
docker push 422240912951.dkr.ecr.us-east-1.amazonaws.com/poprox_web:latest
