for file in $(ls *.csv)
do
    table_name="${file%.*}"
    column_names=$(head -n1 $file | sed -e 's/\r//g')
    sql_statement="COPY $table_name ($column_names) FROM '/tmp/$file' WITH DELIMITER ',' CSV HEADER;"
    # use this to echo out all the psql commands instead of running them.
    echo "psql --dbname remarkbox -c \"$sql_statement\""
done


# this is an example importing a single table from a CSV file.
#psql --dbname remarkbox -c "COPY rb_user (id,name,email,password,created,gravatar,verified,disabled,admin,email_id,password_timestamp) FROM 'rb_user.csv' WITH DELIMITER ',' CSV HEADER;
