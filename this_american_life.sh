#!/bin/bash

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <episode number>"
  exit 1
fi

EPISODE=$1

wget https://www.podtrac.com/pts/redirect.mp3/podcast.thisamericanlife.org/podcast/${EPISODE}.mp3
mv ${EPISODE}.mp3 ${EPISODE}_original.mp3

mkdir ${EPISODE}
pushd ${EPISODE}

FILES=""
COUNT=0

while [ 1 ]
do
  PADDED_COUNT=$(printf %03d ${COUNT})
  wget -nv https://stream.thisamericanlife.org/${EPISODE}/stream/${EPISODE}_64k_${PADDED_COUNT}.ts || break
  FILES="${FILES} ${EPISODE}/${EPISODE}_64k_${PADDED_COUNT}.ts"
  (( COUNT++ ))
done

popd
tar cJf ${EPISODE}.tar.bz ${EPISODE}

/Applications/VLC.app/Contents/MacOS/VLC -I rc -I dummy ${FILES} vlc://quit --sout "#gather:transcode{acodec=mp3,ab=64}:std{access=file,dst=${EPISODE}.mp3}" --sout-keep

rm -rf ${EPISODE}
