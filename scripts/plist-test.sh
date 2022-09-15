#!/usr/bin/env bash
#
# Copyright (c) 2022 iterate GmbH. All rights reserved.
# https://cyberduck.io/
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
set -e

DIRECTORY=$1
if [ ! ${DIRECTORY} ]; then
  DIRECTORY=$(dirname "$(cd -P -- "$(dirname -- "$0")" && pwd -P)")
fi
echo "Finding profiles in ${DIRECTORY}"

for path in ${DIRECTORY}/*.cyberduckprofile; do
  filename=$(basename "${path}")
  echo "XML Sanity check ${filename}"
  MESSAGE=$(plistutil -i "${path}" -o /dev/null)
  if [[ ${MESSAGE} =~ ^ERROR: ]]; then
  	echo ${MESSAGE}
  	exit 1
  fi
done
